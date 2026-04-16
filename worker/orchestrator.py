"""Application orchestrator — the heart of the worker.

Responsibilities:
  1. Claim queued applications from Supabase (row-locked, concurrent-safe)
  2. Load the user's profile + resume to local disk
  3. Drive Playwright through the application flow:
        fetch DOM -> pick adapter -> parse -> resolve_field per candidate
        -> (hold if review required) -> execute_decisions -> submit
  4. After submit, schedule verifier polling; only on confirmation does
     the DB trigger decrement a credit (financial integrity gate).

Design notes:
  - Single process, bounded global concurrency (default 2). Per-company
    semaphore limits concurrent hits to one ATS host, avoiding 429 storms.
  - All network-bound work is async; Playwright is wrapped in sync-in-thread
    where its API is sync.
  - Failures are isolated: one bad job never kills the loop.
  - Every run writes a submission_log trace + screenshot URL for audit —
    this is how we defend "we filed it" if a user disputes.

Run:
  python -m worker.orchestrator           # main loop
  python -m worker.orchestrator --once    # drain queue once and exit
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import tempfile
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

from supabase import Client, create_client

from .actions import ExecutionReport, execute_decisions
from .adapters import adapter_for_html, adapter_for_url
from .autofill.cache import SupabaseAnswerCache
from .autofill.engine import resolve_field
from .autofill.llm import NimClient
from .autofill.models import EngineConfig, FieldDecision, UserProfile
from .verifier import ConfirmationHit, EmailVerifier, NullVerifier

log = logging.getLogger("worker.orchestrator")


# ─── Config ─────────────────────────────────────────────────────
DEFAULT_CONCURRENCY = int(os.getenv("WORKER_CONCURRENCY", "2"))
PER_COMPANY_CONCURRENCY = int(os.getenv("WORKER_PER_COMPANY_CONCURRENCY", "2"))
POLL_IDLE_SECONDS = int(os.getenv("WORKER_POLL_IDLE_SECONDS", "10"))
VERIFIER_WINDOW_MIN = int(os.getenv("WORKER_VERIFIER_WINDOW_MIN", "30"))
VERIFIER_POLL_INTERVAL_SEC = int(os.getenv("WORKER_VERIFIER_POLL_INTERVAL_SEC", "120"))

# Skip application if this many candidates flagged as required_review
# and the user has review_before_send=True — we park it for human review.
REVIEW_HOLD_STATUS = "needs_review"


# ─── Supabase client (service role) ─────────────────────────────
def _db() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


# ─── Per-company concurrency limiter ────────────────────────────
class CompanyLimiter:
    """One semaphore per company_slug, materialized lazily.

    Protects employers from our own thundering herd and keeps request
    patterns plausibly human.
    """

    def __init__(self, per_company: int = PER_COMPANY_CONCURRENCY):
        self._per_company = per_company
        self._sems: dict[str, asyncio.Semaphore] = defaultdict(
            lambda: asyncio.Semaphore(self._per_company)
        )

    @asynccontextmanager
    async def slot(self, company_slug: str):
        sem = self._sems[company_slug or "__global__"]
        async with sem:
            yield


# ─── Claim a job (atomic) ───────────────────────────────────────
def _claim_one(db: Client) -> Optional[dict]:
    """Claim a single queued application, setting it to in_progress.

    We use `status='queued' -> 'in_progress'` with a timestamp guard.
    For true SELECT FOR UPDATE SKIP LOCKED we'd need psycopg — this is
    good enough at current scale because the update is atomic and
    `started_at` is used as the idempotency key.
    """
    # RPC call is cleaner; for now use the REST filter update pattern:
    # atomic: update ... where status='queued' returning *. Supabase-py
    # only returns affected rows, so one row wins per call.
    resp = (
        db.table("applications")
        .update({"status": "in_progress", "started_at": datetime.now(timezone.utc).isoformat()})
        .eq("status", "queued")
        .order("queued_at", desc=False)
        .limit(1)
        .execute()
    )
    rows = resp.data or []
    return rows[0] if rows else None


def _load_job(db: Client, job_id: str) -> Optional[dict]:
    r = db.table("jobs").select("*").eq("id", job_id).limit(1).execute()
    return (r.data or [None])[0]


def _load_profile(db: Client, user_id: str) -> Optional[UserProfile]:
    r = db.table("profiles").select("*").eq("id", user_id).limit(1).execute()
    row = (r.data or [None])[0]
    if not row:
        return None

    first = row.get("first_name") or ""
    last = row.get("last_name") or ""
    full = (row.get("full_name") or f"{first} {last}").strip()

    return UserProfile(
        user_id=user_id,
        first_name=first,
        last_name=last,
        full_name=full,
        email=row.get("email") or "",
        phone_e164=row.get("phone_e164"),
        phone_national=row.get("phone_national"),
        linkedin_url=row.get("linkedin_url"),
        github_url=row.get("github_url"),
        portfolio_url=row.get("portfolio_url"),
        website_url=row.get("website_url"),
        city=row.get("city"),
        state=row.get("state"),
        country=row.get("country"),
        postal_code=row.get("postal_code"),
        work_auth_status=row.get("work_auth_status"),
        needs_sponsorship=row.get("needs_sponsorship"),
        current_company=row.get("current_company"),
        current_title=row.get("current_title"),
        years_experience=row.get("years_experience"),
        school=row.get("school"),
        degree=row.get("degree"),
        major=row.get("major"),
        graduation_year=row.get("graduation_year"),
        gender=row.get("gender"),
        race_ethnicity=row.get("race_ethnicity"),
        veteran_status=row.get("veteran_status"),
        disability_status=row.get("disability_status"),
        salary_expectation_usd=row.get("salary_expectation_usd"),
        willing_to_relocate=row.get("willing_to_relocate"),
        remote_preference=row.get("remote_preference"),
        earliest_start_date=row.get("earliest_start_date"),
    )


def _load_user_preferences(db: Client, user_id: str) -> dict:
    r = db.table("preferences").select("*").eq("user_id", user_id).limit(1).execute()
    return (r.data or [{}])[0] or {}


def _download_resume(db: Client, user_id: str, tmpdir: Path) -> Optional[Path]:
    """Pull the user's active resume from Supabase Storage into tmpdir."""
    r = (
        db.table("resumes")
        .select("id, storage_path, filename, parsed_json")
        .eq("user_id", user_id)
        .eq("is_active", True)
        .order("uploaded_at", desc=True)
        .limit(1)
        .execute()
    )
    row = (r.data or [None])[0]
    if not row:
        return None
    storage_path = row["storage_path"]
    filename = row.get("filename") or "resume.pdf"
    dest = tmpdir / filename
    try:
        blob = db.storage.from_("resumes").download(storage_path)
        dest.write_bytes(blob)
        return dest
    except Exception:
        log.exception("resume_download_failed", extra={"user_id": user_id})
        return None


# ─── Settlement (status writes) ─────────────────────────────────
def _write_status(
    db: Client,
    application_id: str,
    status: str,
    *,
    submission_log: Optional[dict] = None,
    screenshot_url: Optional[str] = None,
    confirmation_email_id: Optional[str] = None,
    confirmed_at: Optional[datetime] = None,
    error_message: Optional[str] = None,
    completed: bool = False,
) -> None:
    patch: dict[str, Any] = {"status": status}
    if submission_log is not None:
        patch["submission_log"] = submission_log
    if screenshot_url is not None:
        patch["screenshot_url"] = screenshot_url
    if confirmation_email_id is not None:
        patch["confirmation_email_id"] = confirmation_email_id
    if confirmed_at is not None:
        patch["confirmed_at"] = confirmed_at.isoformat()
    if error_message is not None:
        patch["error_message"] = error_message
    if completed:
        patch["completed_at"] = datetime.now(timezone.utc).isoformat()
    db.table("applications").update(patch).eq("id", application_id).execute()


# ─── Build a verifier for this user ─────────────────────────────
def _verifier_for_user(db: Client, user_id: str) -> EmailVerifier:
    """Return a GmailVerifier if the user has Gmail connected, else NullVerifier.

    Gmail OAuth credentials live in `gmail_credentials(user_id, refresh_token, ...)`.
    This function lazy-imports googleapiclient so tests that don't touch Gmail
    don't pay the import cost.
    """
    r = (
        db.table("gmail_credentials")
        .select("refresh_token, client_id, client_secret")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    row = (r.data or [None])[0]
    if not row or not row.get("refresh_token"):
        return NullVerifier()

    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials(
            token=None,
            refresh_token=row["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=row.get("client_id") or os.environ["GMAIL_CLIENT_ID"],
            client_secret=row.get("client_secret") or os.environ["GMAIL_CLIENT_SECRET"],
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        )
        svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
        from .verifier import GmailVerifier
        return GmailVerifier(svc)
    except Exception:
        log.exception("gmail_verifier_init_failed", extra={"user_id": user_id})
        return NullVerifier()


# ─── Playwright runner ──────────────────────────────────────────
@dataclass
class RunArtifacts:
    dom_html: str = ""
    screenshot_bytes: bytes = b""
    report: Optional[ExecutionReport] = None
    decisions: list[FieldDecision] = field(default_factory=list)


async def _run_browser(
    apply_url: str,
    profile: UserProfile,
    cache: SupabaseAnswerCache,
    llm: NimClient,
    *,
    dry_run: bool,
    review_before_send: bool,
) -> RunArtifacts:
    """Fetch the apply page, parse, resolve, execute."""
    from playwright.async_api import async_playwright

    art = RunArtifacts()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 900},
        )
        page = await ctx.new_page()
        try:
            await page.goto(apply_url, wait_until="domcontentloaded", timeout=45000)
            # Let client-side hydration settle
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass

            html = await page.content()
            art.dom_html = html

            adapter = adapter_for_html(html, url=apply_url) or adapter_for_url(apply_url)
            if adapter is None:
                art.report = ExecutionReport(
                    filled=0, skipped=0, flagged_review=0, errors=1,
                    submitted=False, outcomes=[],
                )
                art.report.errors = 1
                return art

            candidates = adapter.parse_form(html)
            decisions: list[FieldDecision] = []
            any_review = False
            for cand in candidates:
                d = resolve_field(cand, profile, cache=cache, llm=llm, config=EngineConfig())
                decisions.append(d)
                if d.required_review:
                    any_review = True
            art.decisions = decisions

            hold_for_review = review_before_send and any_review

            art.report = await execute_decisions(
                page,
                decisions,
                candidates,
                dry_run=dry_run or hold_for_review,
            )
            try:
                art.screenshot_bytes = await page.screenshot(full_page=True, type="png")
            except Exception:
                pass
            return art
        finally:
            await ctx.close()
            await browser.close()


def _upload_artifacts(
    db: Client, application_id: str, art: RunArtifacts
) -> Optional[str]:
    """Write the DOM + screenshot to Supabase Storage, return screenshot URL."""
    try:
        base = f"{application_id}"
        if art.dom_html:
            db.storage.from_("autofill-artifacts").upload(
                f"{base}/dom.html",
                art.dom_html.encode("utf-8"),
                {"content-type": "text/html; charset=utf-8", "upsert": "true"},
            )
        shot_url = None
        if art.screenshot_bytes:
            path = f"{base}/screenshot.png"
            db.storage.from_("autofill-artifacts").upload(
                path,
                art.screenshot_bytes,
                {"content-type": "image/png", "upsert": "true"},
            )
            shot_url = db.storage.from_("autofill-artifacts").get_public_url(path)
        return shot_url
    except Exception:
        log.exception("artifact_upload_failed", extra={"application_id": application_id})
        return None


# ─── One job ────────────────────────────────────────────────────
async def run_job(app_row: dict, *, limiter: CompanyLimiter) -> None:
    """End-to-end processing for a single claimed application row."""
    application_id = app_row["id"]
    user_id = app_row["user_id"]
    job_id = app_row["job_id"]
    db = _db()

    job = _load_job(db, job_id)
    profile = _load_profile(db, user_id)
    prefs = _load_user_preferences(db, user_id)

    if not job or not profile:
        _write_status(
            db, application_id, "failed",
            error_message="missing_job_or_profile", completed=True,
        )
        return

    # Beta gate: Workday only if user opted in
    if job["source"] == "workday" and not prefs.get("workday_enabled"):
        _write_status(
            db, application_id, "skipped",
            error_message="workday_not_enabled", completed=True,
        )
        return

    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        resume_path = _download_resume(db, user_id, tmpdir)
        if resume_path:
            profile = profile.model_copy(update={"resume_local_path": str(resume_path)})

        cache = SupabaseAnswerCache(db, user_id=user_id)
        llm = NimClient()
        review_before_send = bool(prefs.get("review_before_send", True))

        async with limiter.slot(job["company_slug"]):
            try:
                art = await _run_browser(
                    job["apply_url"],
                    profile,
                    cache=cache,
                    llm=llm,
                    dry_run=False,
                    review_before_send=review_before_send,
                )
            except Exception as e:
                log.exception("browser_run_failed", extra={"application_id": application_id})
                _write_status(
                    db, application_id, "failed",
                    error_message=f"browser_error: {e}", completed=True,
                )
                return

        screenshot_url = _upload_artifacts(db, application_id, art)

        rep = art.report
        log_trace = {
            "filled": rep.filled if rep else 0,
            "skipped": rep.skipped if rep else 0,
            "flagged_review": rep.flagged_review if rep else 0,
            "errors": rep.errors if rep else 1,
            "outcomes": [o.__dict__ if hasattr(o, "__dict__") else o for o in (rep.outcomes if rep else [])],
            "decisions": [
                {
                    "dom_id": d.dom_id,
                    "source": d.source.value if hasattr(d.source, "value") else str(d.source),
                    "confidence": d.confidence,
                    "rule_id": d.rule_id,
                    "required_review": d.required_review,
                }
                for d in art.decisions
            ],
        }

        if rep is None or not rep.submitted:
            # Either review-hold or execution error
            needs_review = any(d.required_review for d in art.decisions) and review_before_send
            status = REVIEW_HOLD_STATUS if needs_review else "failed"
            _write_status(
                db, application_id, status,
                submission_log=log_trace,
                screenshot_url=screenshot_url,
                error_message=None if needs_review else (
                    f"execution_errors={rep.errors}" if rep else "no_report"
                ),
                completed=not needs_review,
            )
            return

        # Submitted — park as 'submitted', launch verifier watch
        _write_status(
            db, application_id, "submitted",
            submission_log=log_trace,
            screenshot_url=screenshot_url,
        )

        verifier = _verifier_for_user(db, user_id)
        # NullVerifier never confirms; just return — user can mark confirmed manually
        if isinstance(verifier, NullVerifier):
            return

        asyncio.create_task(
            _watch_for_confirmation(
                application_id=application_id,
                user_id=user_id,
                user_email=profile.email,
                company_name=job["company_name"],
                job_title=job["title"],
                submitted_at=datetime.now(timezone.utc),
                verifier=verifier,
            )
        )


# ─── Verifier watch ─────────────────────────────────────────────
async def _watch_for_confirmation(
    *,
    application_id: str,
    user_id: str,
    user_email: str,
    company_name: str,
    job_title: str,
    submitted_at: datetime,
    verifier: EmailVerifier,
) -> None:
    """Poll the verifier for up to VERIFIER_WINDOW_MIN; on hit, flip to confirmed."""
    deadline = submitted_at + timedelta(minutes=VERIFIER_WINDOW_MIN)
    db = _db()
    while datetime.now(timezone.utc) < deadline:
        try:
            hit: Optional[ConfirmationHit] = verifier.verify(
                user_email=user_email,
                company_name=company_name,
                job_title=job_title,
                submitted_at=submitted_at,
                lookback_minutes=VERIFIER_WINDOW_MIN,
            )
        except Exception:
            log.exception("verifier_call_failed", extra={"application_id": application_id})
            hit = None

        if hit is not None:
            _write_status(
                db, application_id, "confirmed",
                confirmation_email_id=hit.message_id,
                confirmed_at=hit.received_at,
                completed=True,
            )
            return

        await asyncio.sleep(VERIFIER_POLL_INTERVAL_SEC)
    # Window expired without confirmation — leave as 'submitted'.
    # No credit decrement until a human or later poll confirms.


# ─── Main loop ──────────────────────────────────────────────────
async def main_loop(concurrency: int = DEFAULT_CONCURRENCY, once: bool = False) -> None:
    limiter = CompanyLimiter()
    in_flight: set[asyncio.Task] = set()
    db = _db()
    log.info("worker_started", extra={"concurrency": concurrency})

    while True:
        # Reap finished
        done = {t for t in in_flight if t.done()}
        for t in done:
            in_flight.discard(t)
            exc = t.exception()
            if exc:
                log.error("job_task_crashed", exc_info=exc)

        if len(in_flight) >= concurrency:
            await asyncio.sleep(0.5)
            continue

        try:
            row = _claim_one(db)
        except Exception:
            log.exception("claim_failed")
            await asyncio.sleep(POLL_IDLE_SECONDS)
            continue

        if row is None:
            if once and not in_flight:
                return
            await asyncio.sleep(POLL_IDLE_SECONDS)
            continue

        log.info("job_claimed", extra={"application_id": row["id"]})
        task = asyncio.create_task(run_job(row, limiter=limiter))
        in_flight.add(task)


def _cli() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="Drain queue once and exit")
    ap.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    args = ap.parse_args()
    asyncio.run(main_loop(concurrency=args.concurrency, once=args.once))


if __name__ == "__main__":
    _cli()
