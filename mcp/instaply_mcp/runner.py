"""Local Playwright runner — the v0.3 piece that actually fills + submits.

Wires the vendored worker engine to the MCP package's local SQLite
store. The MCP `apply_to_job` tool calls into here to do the real work
on the user's machine: launch Chromium (visible by default so the
user can solve any captcha), detect the ATS adapter, parse the form,
resolve each field via the rules engine + answer-vault cache + LLM
fallback, fill it, and pause for the user to solve verification before
the user clicks Submit themselves.

Crucially: the runner NEVER clicks Submit for the user. The honest
contract is "Instaply fills, you confirm + submit." Captcha-bypass is
out of scope by policy.

Cost-of-first-call: Playwright Chromium auto-installs ~150 MB on
first run. Subsequent runs reuse it.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Optional

from . import db
from ._worker.adapters.greenhouse import GreenhouseAdapter
from ._worker.adapters.lever import LeverAdapter
from ._worker.adapters.smartrecruiters import SmartRecruitersAdapter
from ._worker.autofill.cache import field_question, question_hash
from ._worker.autofill.engine import resolve_field
from ._worker.autofill.models import (
    DecisionSource,
    EngineConfig,
    FieldCandidate,
    UserProfile,
)


# ─── SQLite-backed AnswerCache (matches the worker's Protocol) ──
class LocalAnswerCache:
    """Reads + writes the answer vault in our local SQLite store.

    Honors the same hash-key contract the hosted SaaS worker uses
    (see `db.question_hash`), so a future "import from dashboard"
    tool can move rows over without re-keying.
    """

    def lookup(self, user_id: str, question: str, company_slug: Optional[str] = None):
        # Single-user local case → user_id is ignored. Company_slug
        # is also ignored for v0.3; we treat the local answer vault
        # as user-scoped global. Future versions may add scoping.
        text = db.lookup_answer(question)
        if not text:
            return None
        # Mirror the SupabaseAnswerCache return shape (engine.py
        # expects a CachedAnswer-like with `answer`, `confidence`,
        # `model`, `source_company_slug`).
        from ._worker.autofill.cache import CachedAnswer
        return CachedAnswer(
            answer=text,
            confidence=0.85,
            model=None,
            source_company_slug=None,
        )

    def store(
        self,
        user_id: str,
        question: str,
        answer: str,
        confidence: float,
        model: Optional[str],
        field_type: str,
        company_slug: Optional[str] = None,
    ) -> None:
        db.save_answer(question, answer)


# ─── Profile bridge ─────────────────────────────────────────────
def _build_user_profile(local_profile: dict[str, Any], application_id: str) -> UserProfile:
    """Adapt the local profile dict to the worker's UserProfile model."""
    return UserProfile(
        user_id=application_id,  # local case — any stable string works
        first_name=local_profile.get("first_name") or (local_profile.get("full_name") or " ").split(" ")[0],
        last_name=local_profile.get("last_name") or " ".join((local_profile.get("full_name") or "").split(" ")[1:]) or "",
        full_name=local_profile.get("full_name") or "",
        email=local_profile.get("email") or "",
        phone_e164=local_profile.get("phone_e164") or local_profile.get("phone"),
        phone_national=local_profile.get("phone_national") or local_profile.get("phone"),
        linkedin_url=local_profile.get("linkedin_url"),
        github_url=local_profile.get("github_url"),
        portfolio_url=local_profile.get("portfolio_url") or local_profile.get("website_url"),
        website_url=local_profile.get("website_url"),
        city=local_profile.get("city") or local_profile.get("current_city"),
        state=local_profile.get("state") or local_profile.get("current_state"),
        country=local_profile.get("country") or local_profile.get("current_country"),
        postal_code=local_profile.get("postal_code") or local_profile.get("zip_code"),
        work_auth_status=local_profile.get("work_auth_status"),
        needs_sponsorship=local_profile.get("needs_sponsorship"),
        current_company=local_profile.get("current_company"),
        current_title=local_profile.get("current_title"),
        years_experience=local_profile.get("years_experience"),
        school=local_profile.get("school"),
        degree=local_profile.get("degree"),
        major=local_profile.get("major"),
        graduation_year=local_profile.get("graduation_year"),
        gender=local_profile.get("gender"),
        pronouns=local_profile.get("pronouns"),
        race_ethnicity=local_profile.get("race_ethnicity") or local_profile.get("race"),
        veteran_status=local_profile.get("veteran_status"),
        disability_status=local_profile.get("disability_status"),
        salary_expectation_usd=local_profile.get("salary_expectation_usd"),
        willing_to_relocate=local_profile.get("willing_to_relocate"),
        resume_local_path=local_profile.get("resume_local_path"),
        resume_parsed_json=local_profile.get("extracted_skills") or local_profile.get("resume_parsed_json"),
        resume_text_excerpt=(local_profile.get("resume_text_excerpt") or local_profile.get("resume_text") or "")[:4000] or None,
    )


# ─── Adapter detection ──────────────────────────────────────────
ADAPTERS = [GreenhouseAdapter(), LeverAdapter(), SmartRecruitersAdapter()]


def _pick_adapter(url: str, html: str):
    for a in ADAPTERS:
        try:
            if a.detect_url(url) or a.detect_html(html):
                return a
        except Exception:
            continue
    return None


# ─── Public entrypoint ──────────────────────────────────────────
async def apply_locally(
    application_id: str,
    apply_url: str,
    *,
    headless: bool = False,
) -> dict[str, Any]:
    """Open the apply page in the user's browser, fill what we can,
    leave the user to solve any captcha and click Submit.

    Returns a dict the MCP tool can pass back to the model:
      {
        ok: bool,
        adapter: 'greenhouse' | 'lever' | 'smartrecruiters' | None,
        filled: int,
        needs_review: list[{question, suggested}],
        message: str,
      }

    Headless defaults to False because the whole point is the user
    solves captcha in their own visible Chrome.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {
            "ok": False,
            "error": "playwright_not_installed",
            "message": (
                "Playwright isn't installed. Run:\n"
                "  pip install 'instaply-mcp[worker]'\n"
                "  python -m playwright install chromium\n"
                "Then call apply_to_job again."
            ),
        }

    profile = db.get_profile()
    if not profile.get("full_name") or not profile.get("email"):
        return {
            "ok": False,
            "error": "profile_incomplete",
            "message": "Set at least full_name and email via update_profile before applying.",
        }

    db.update_application(
        application_id,
        status="in_progress",
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    user_profile = _build_user_profile(profile, application_id)
    cache = LocalAnswerCache()
    config = EngineConfig()

    adapter_kind = None
    filled_count = 0
    needs_review: list[dict[str, Any]] = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto(apply_url, wait_until="domcontentloaded", timeout=30000)

            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass

            html = await page.content()
            adapter = _pick_adapter(apply_url, html)
            if adapter is None:
                db.update_application(
                    application_id,
                    status="failed",
                    error_message="no_supported_adapter",
                    completed_at=datetime.now(timezone.utc).isoformat(),
                )
                await browser.close()
                return {
                    "ok": False,
                    "error": "no_supported_adapter",
                    "message": "This URL isn't a Greenhouse, Lever, or SmartRecruiters page. Open it manually for now.",
                }
            adapter_kind = getattr(adapter, "kind", None)
            adapter_kind_str = str(adapter_kind.value if hasattr(adapter_kind, "value") else adapter_kind)

            candidates = adapter.parse_form(html)

            for cand in candidates:
                try:
                    decision = resolve_field(cand, user_profile, cache=cache, llm=None, config=config)
                except Exception as e:
                    needs_review.append({
                        "question": field_question(cand) or cand.dom_id,
                        "suggested": None,
                        "error": str(e)[:120],
                    })
                    continue
                if decision.source in (DecisionSource.SKIP, DecisionSource.REVIEW):
                    needs_review.append({
                        "question": field_question(cand) or cand.dom_id,
                        "suggested": decision.value,
                    })
                    continue
                if decision.required_review:
                    needs_review.append({
                        "question": field_question(cand) or cand.dom_id,
                        "suggested": decision.value,
                    })
                # Best-effort fill via Playwright: we don't import the
                # full execute_decisions because that one also clicks
                # Submit. Local v0.3 contract is fill-only; the user
                # clicks Submit. So we do a minimal type-into-input.
                try:
                    selector = f'#{cand.dom_id}' if cand.id_attr else f'[name="{cand.name_attr}"]'
                    el = await page.query_selector(selector)
                    if el and decision.value not in (None, ""):
                        await el.fill(str(decision.value))
                        filled_count += 1
                except Exception:
                    pass

            db.update_application(
                application_id,
                status="needs_review" if needs_review else "in_progress",
                submission_log={
                    "filled_fields": filled_count,
                    "needs_review": needs_review,
                    "adapter": adapter_kind_str,
                },
            )
            # Leave the browser OPEN so the user can review, solve any
            # captcha, and click Submit themselves. The runner returns
            # immediately; the application record stays as
            # `in_progress` / `needs_review` until the user calls
            # `mark_complete` (manual finish) or the optional
            # confirmation observer (future) fires.
            return {
                "ok": True,
                "adapter": adapter_kind_str,
                "filled": filled_count,
                "needs_review_count": len(needs_review),
                "needs_review": needs_review[:20],
                "message": (
                    f"Opened the application in your browser and filled {filled_count} field(s). "
                    f"{len(needs_review)} item(s) need your review. "
                    "Solve any captcha, double-check the form, then click Submit yourself. "
                    "When the employer's confirmation page appears, call mark_complete."
                ),
            }
    except Exception as e:
        db.update_application(
            application_id,
            status="failed",
            error_message=f"runner_exception: {type(e).__name__}: {str(e)[:200]}",
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        return {"ok": False, "error": "runner_exception", "message": str(e)[:200]}


def apply_locally_sync(application_id: str, apply_url: str, headless: bool = False) -> dict[str, Any]:
    """Sync wrapper for the MCP tool layer (which is sync from server.py)."""
    return asyncio.run(apply_locally(application_id, apply_url, headless=headless))
