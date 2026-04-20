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
from .adapters.base import AtsKind
from .autofill.cache import SupabaseAnswerCache, field_question
from .autofill.engine import resolve_field
from .autofill.llm import CerebrasClient
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
# ─── Feature-flag gating (canary rollout) ───────────────────────
# This worker only claims applications belonging to users who have
# explicitly opted in via `preferences.use_native_worker = true` (see
# migration 0015). Until at least one user is opted in, the worker is
# inert — it polls and finds nothing, leaving every queued app for the
# legacy Revize-imported submitter (`instaply-submitter` Fly app) to
# pick up. This makes deploying `instaply-worker` zero-risk for
# existing users on day one.
_OPTED_IN_CACHE: dict[str, Any] = {"ids": [], "ts": 0.0}
_OPTED_IN_TTL_SECONDS = float(os.getenv("WORKER_OPTED_IN_TTL_SECONDS", "60"))


def _opted_in_user_ids(db: Client, *, force_refresh: bool = False) -> list[str]:
    """Return the list of user_ids currently opted into the native worker.

    Cached for `_OPTED_IN_TTL_SECONDS` to avoid hammering `preferences`
    on every claim attempt. Fail-closed: if the lookup raises (e.g.
    transient network), we return the LAST cached value rather than
    accidentally claiming nothing — the alternative (returning `[]`)
    would freeze the worker silently on a hiccup.
    """
    now = time.time()
    if not force_refresh and (now - _OPTED_IN_CACHE["ts"] < _OPTED_IN_TTL_SECONDS):
        return list(_OPTED_IN_CACHE["ids"])
    try:
        resp = (
            db.table("preferences")
            .select("user_id")
            .eq("use_native_worker", True)
            .execute()
        )
        ids = [r["user_id"] for r in (resp.data or []) if r.get("user_id")]
        _OPTED_IN_CACHE["ids"] = ids
        _OPTED_IN_CACHE["ts"] = now
        return list(ids)
    except Exception:
        log.exception("opted_in_lookup_failed")
        return list(_OPTED_IN_CACHE["ids"])


def _claim_one(db: Client) -> Optional[dict]:
    """Claim a single queued application from an opted-in user.

    Atomicity: the UPDATE is a single SQL statement with WHERE
    `status='queued' AND user_id IN (opted_in)` ORDER BY queued_at
    LIMIT 1 RETURNING *. PostgREST evaluates the filter at update time,
    so even if the legacy Revize submitter races us, only one PATCH
    transitions any given row from `queued` → `in_progress` — the
    other's filter no longer matches and returns zero rows.

    If no users are opted in, return None immediately (no DB roundtrip
    for the UPDATE itself, just the cached preferences lookup).
    """
    opted_in = _opted_in_user_ids(db)
    if not opted_in:
        return None
    # Two-step claim: SELECT the oldest queued candidate ordered by FIFO,
    # then issue an atomic compare-and-set UPDATE by id. Supabase-py
    # >=2.13 removed `.order()` from the UPDATE chain, so we can't do it
    # in one statement anymore — but the UPDATE is still atomic against
    # any other contender thanks to the `.eq("status","queued")` guard.
    sel = (
        db.table("applications")
        .select("id")
        .eq("status", "queued")
        .in_("user_id", opted_in)
        .order("queued_at", desc=False)
        .limit(1)
        .execute()
    )
    candidates = sel.data or []
    if not candidates:
        return None
    app_id = candidates[0]["id"]
    resp = (
        db.table("applications")
        .update({"status": "in_progress", "started_at": datetime.now(timezone.utc).isoformat()})
        .eq("id", app_id)
        .eq("status", "queued")  # atomic guard — only wins if still queued
        .execute()
    )
    rows = resp.data or []
    return rows[0] if rows else None


def _load_job(db: Client, job_id: str) -> Optional[dict]:
    r = db.table("jobs").select("*").eq("id", job_id).limit(1).execute()
    return (r.data or [None])[0]


def _load_profile(db: Client, user_id: str) -> Optional[UserProfile]:
    """Load a UserProfile from the production Instaply schema.

    Schema notes (see supabase/migrations/0001_init.sql + 0013):
      - `profiles` stores `full_name` (not first/last), `phone` (single
        column, not e164/national split), `current_city`/`current_state`/
        `current_country`/`zip_code`, and `race` (not `race_ethnicity`).
      - Experience-level and salary preferences live in `preferences`
        (years_of_experience, salary_min_usd, start_availability, etc.).
      - Education, titles held, industries, and experience_years fallback
        live in `profiles.extracted_skills` (jsonb, resume-parser output).

    Missing-from-schema fields (current_company, current_title, etc.)
    are set to None. The autofill engine tolerates None and will either
    defer to the LLM or flag for review.
    """
    r = db.table("profiles").select("*").eq("id", user_id).limit(1).execute()
    row = (r.data or [None])[0]
    if not row:
        return None

    # Preferences live in a sibling table — fetch once, tolerate absence.
    try:
        pr = db.table("preferences").select("*").eq("user_id", user_id).limit(1).execute()
        prefs = (pr.data or [{}])[0] or {}
    except Exception:
        prefs = {}

    # extracted_skills is the resume-parser's structured output (jsonb).
    skills = row.get("extracted_skills") or {}
    if not isinstance(skills, dict):
        skills = {}
    education = skills.get("education") or {}
    if not isinstance(education, dict):
        education = {}

    # Split full_name -> first/last. Instaply schema only stores full_name.
    full = (row.get("full_name") or "").strip()
    parts = full.split(None, 1)
    first = parts[0] if parts else ""
    last = parts[1] if len(parts) > 1 else ""

    # Single phone column in Instaply schema. Use it for both slots the
    # UserProfile model exposes (callers read whichever is populated).
    phone = row.get("phone") or None

    # Defensive int coercion — jsonb education fields can be strings.
    def _as_int(v: Any) -> Optional[int]:
        if v is None or v == "":
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    # Start availability → approximate ISO date (engine uses as-is).
    start_label = prefs.get("start_availability") or "immediately"
    now_utc = datetime.now(timezone.utc)
    start_map = {
        "immediately": now_utc.date().isoformat(),
        "2_weeks": (now_utc + timedelta(days=14)).date().isoformat(),
        "1_month": (now_utc + timedelta(days=30)).date().isoformat(),
        "flexible": None,
    }
    earliest_start = start_map.get(start_label)

    # Years of experience — preferences takes precedence, fall back to
    # the resume-parser's inferred value in extracted_skills.
    years_exp = _as_int(prefs.get("years_of_experience"))
    if years_exp is None:
        years_exp = _as_int(skills.get("experience_years"))

    # Remote preference is stored as boolean `remote_ok` on preferences.
    remote_pref: Optional[str] = None
    if prefs.get("remote_ok") is True:
        remote_pref = "remote"

    return UserProfile(
        user_id=user_id,
        first_name=first,
        last_name=last,
        full_name=full,
        email=row.get("email") or "",
        # Single phone column in Instaply — populate both model slots.
        phone_e164=phone,
        phone_national=phone,
        linkedin_url=row.get("linkedin_url"),
        github_url=row.get("github_url"),
        # `portfolio_url` is not a separate column; website_url serves both.
        portfolio_url=row.get("website_url"),
        website_url=row.get("website_url"),
        # Location — Instaply schema uses `current_*` + `zip_code`.
        city=row.get("current_city"),
        state=row.get("current_state"),
        country=row.get("current_country") or "United States",
        postal_code=row.get("zip_code"),
        work_auth_status=row.get("work_auth_status"),
        needs_sponsorship=row.get("needs_sponsorship"),
        # Not stored in Instaply profiles schema today.
        current_company=None,
        current_title=None,
        years_experience=years_exp,
        # Education fields come from the resume parser's extracted_skills.
        school=education.get("school"),
        degree=education.get("degree"),
        major=education.get("major"),
        graduation_year=_as_int(education.get("graduation_year")),
        gender=row.get("gender"),
        # Pronouns: distinct from gender. Read straight; never derive.
        pronouns=row.get("pronouns"),
        # Schema column is `race`, not `race_ethnicity`.
        race_ethnicity=row.get("race"),
        veteran_status=row.get("veteran_status"),
        disability_status=row.get("disability_status"),
        # Salary expectation lives in preferences, not profiles.
        salary_expectation_usd=_as_int(prefs.get("salary_min_usd")),
        willing_to_relocate=row.get("willing_to_relocate"),
        remote_preference=remote_pref,
        earliest_start_date=earliest_start,
        # Resume-grounding data for the LLM path. `extracted_skills` is the
        # best structured resume evidence we currently have in production, and
        # `resume_text` (when present) is the strongest raw source of truth for
        # custom free-text questions.
        resume_parsed_json=skills or None,
        resume_text_excerpt=(row.get("resume_text") or "")[:4000] or None,
    )


def _load_user_preferences(db: Client, user_id: str) -> dict:
    r = db.table("preferences").select("*").eq("user_id", user_id).limit(1).execute()
    return (r.data or [{}])[0] or {}


def _download_resume(db: Client, user_id: str, tmpdir: Path) -> Optional[Path]:
    """Pull the user's primary resume from Supabase Storage into tmpdir.

    Schema (supabase/migrations/0001_init.sql):
      resumes(id, user_id, label, storage_path, file_name, file_size_bytes,
              parsed_json, is_primary, created_at)

    Note: no `is_active` or `uploaded_at` or `filename` columns —
    those are legacy names the worker used to assume.
    """
    r = (
        db.table("resumes")
        .select("id, storage_path, file_name, parsed_json")
        .eq("user_id", user_id)
        .eq("is_primary", True)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    row = (r.data or [None])[0]
    if not row:
        # Fall back to the most recent resume even if no is_primary flag
        # is set (defensive — older accounts may predate the flag).
        r = (
            db.table("resumes")
            .select("id, storage_path, file_name, parsed_json")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        row = (r.data or [None])[0]
        if not row:
            return None
    storage_path = row["storage_path"]
    filename = row.get("file_name") or "resume.pdf"
    dest = tmpdir / filename
    try:
        blob = db.storage.from_("resumes").download(storage_path)
        dest.write_bytes(blob)
        return dest
    except Exception:
        log.exception("resume_download_failed", extra={"user_id": user_id})
        return None


# ─── Settlement (status writes) ─────────────────────────────────
# This worker always tags its writes with submitter_kind='server_instaply'
# so dashboards and per-kind success-rate queries can distinguish it from
# the legacy Revize-imported submitter (which migration 0014 backfills as
# 'server_revize') and the future browser-extension client ('extension').
SUBMITTER_KIND = "server_instaply"


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
    submitter_kind: str = SUBMITTER_KIND,
) -> None:
    """PATCH the applications row with whichever fields are non-None.

    Every column written here is verified against
    supabase/migrations/0001_init.sql + 0014: status, submission_log,
    screenshot_url, confirmation_email_id, confirmed_at, error_message,
    completed_at, submitter_kind. No fields are written that don't
    exist on the live applications table — keeps PATCHes from failing
    silently due to schema drift.
    """
    patch: dict[str, Any] = {
        "status": status,
        # Always stamp the submitter so every Instaply-native row carries
        # its provenance, including `skipped` rows and failure paths.
        "submitter_kind": submitter_kind,
    }
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
    # Human-readable review questions, built per-run from candidates whose
    # decisions ended up `required_review=True` or `source=REVIEW`. Persisted
    # into `submission_log.needs_review` so the dashboard can render the
    # actual question text + Save & Retry input. Without this the UI sees
    # an empty array and renders nothing — root cause of the "I can't see
    # the review question" report from canary on 2026-04-18.
    needs_review: list[dict] = field(default_factory=list)


async def _run_browser(
    apply_url: str,
    profile: UserProfile,
    cache: SupabaseAnswerCache,
    llm: CerebrasClient,
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
            attempted_urls: list[str] = [apply_url]

            # Small remediation: Lever's canonical apply form lives at
            # `<jd_url>/apply`, not on the JD page itself. Many job-board
            # integrations store the JD URL in our `jobs.apply_url`, so
            # `parse_form` returns 0 candidates on the first hit. Re-try
            # once with `/apply` appended before declaring failure.
            if not candidates and getattr(adapter, "kind", None) == AtsKind.LEVER and "/apply" not in apply_url:
                retry_url = apply_url.rstrip("/") + "/apply"
                log.info("lever_retry_with_apply_suffix", extra={"retry_url": retry_url})
                try:
                    await page.goto(retry_url, wait_until="domcontentloaded", timeout=45000)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:
                        pass
                    html = await page.content()
                    art.dom_html = html
                    candidates = adapter.parse_form(html)
                    attempted_urls.append(retry_url)
                except Exception as e:
                    log.warning("lever_retry_failed", extra={"err": str(e), "retry_url": retry_url})

            # Still no candidates → skip execute_decisions entirely and
            # record a clear diagnostic. Calling `execute_decisions` with
            # an empty list would run the submit gate against a page that
            # has no form and produce the useless `execution_errors=0`
            # message the canary run surfaced on Whoop.
            if not candidates:
                empty_report = ExecutionReport(
                    filled=0, skipped=0, flagged_review=0, errors=1,
                    submitted=False, outcomes=[],
                )
                empty_report.submit_reason = (
                    f"no_application_form_found "
                    f"(adapter={getattr(adapter, 'kind', 'unknown')}, "
                    f"tried={attempted_urls})"
                )
                art.report = empty_report
                art.decisions = []
                return art

            decisions: list[FieldDecision] = []
            any_review = False
            review_questions: list[dict] = []
            for cand in candidates:
                d = resolve_field(cand, profile, cache=cache, llm=llm, config=EngineConfig())
                decisions.append(d)
                if d.required_review:
                    any_review = True
                    # Persist the actual question text so the dashboard can
                    # render the Save & Retry input. Use the same question
                    # derivation the cache + answer-vault use, so the
                    # `/answers/save` POST hashes the same key the engine
                    # will look up next time.
                    qtext = field_question(cand)
                    if qtext:
                        review_questions.append({
                            "question": qtext,
                            "kind": (
                                "verify_suggested" if d.value not in (None, "")
                                else "answer_needed"
                            ),
                            "dom_id": cand.dom_id,
                            "suggested": d.value if d.value not in (None, "") else None,
                        })
            art.decisions = decisions
            art.needs_review = review_questions

            hold_for_review = review_before_send and any_review

            art.report = await execute_decisions(
                page,
                decisions,
                candidates,
                dry_run=dry_run or hold_for_review,
                # Pass the matched adapter's submit_selectors so the executor
                # tries Greenhouse/Lever/SmartRecruiters-specific markers
                # instead of only the generic [type=submit] default.
                submit_selectors=getattr(adapter, "submit_selectors", None),
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

        # SupabaseAnswerCache is per-process; user_id is supplied per-call by
        # the engine via lookup(profile.user_id, ...) and store(user_id=...).
        cache = SupabaseAnswerCache(db)
        llm = CerebrasClient()
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
            # Persist the executor's submit-phase signal so the dashboard
            # (and `submission_log->>'submit_reason'` queries) can show
            # why submit succeeded or failed. Added on 2026-04-17 after
            # the Whoop canary showed submit_reason dropped on the floor.
            "submit_reason": getattr(rep, "submit_reason", None) if rep else None,
            "submitted": bool(getattr(rep, "submitted", False)) if rep else False,
            # The dashboard's needs_review render path expects
            # `Array<{question, kind, dom_id, suggested?}>`. Without this
            # key the UI was rendering nothing for review-required rows
            # — testers literally couldn't see the questions to answer.
            # Built per-run inside _run_browser by correlating candidates
            # with decisions that ended up required_review=True.
            "needs_review": list(getattr(art, "needs_review", []) or []),
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
            # Build a user-facing error_message. Priority:
            #   1. rep.submit_reason — the executor's own explanation
            #      (e.g. "no_application_form_found", "submit_click_failed: …",
            #       "no_confirmation_signal via <selector>")
            #   2. `execution_errors=N` if we actually had per-field errors
            #   3. The legacy "no_report" fallback when rep is missing entirely
            # This replaces the old fallback `execution_errors=0` which
            # surfaced on the Whoop canary with no useful signal.
            if rep is None:
                err_msg = "no_report"
            elif rep.submit_reason:
                err_msg = rep.submit_reason
            elif rep.errors > 0:
                err_msg = f"execution_errors={rep.errors}"
            else:
                err_msg = "no_fields_parsed"
            _write_status(
                db, application_id, status,
                submission_log=log_trace,
                screenshot_url=screenshot_url,
                error_message=None if needs_review else err_msg,
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
