"""Auto-apply orchestrator.

Finds jobs with generated application packets, runs autofill+submit via
Playwright, and records tracking entries for successful submissions.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from backend.db.database import get_connection
from backend.db.jobs_repository import mark_job_applied
from backend.services.application_tracker import track_application
from backend.services.autofill import autofill_and_submit
from backend.services.config import settings
from backend.services.files import load_master_resume, load_profile

log = logging.getLogger(__name__)

# Companies on cooldown — maps lowercase company name to unblock date.
# Jobs from these companies are skipped until the date passes.
COMPANY_COOLDOWNS: dict[str, datetime] = {
    "stripe": datetime(2026, 5, 5),  # Hit application limit — 30-day cooldown from Apr 5
    "roblox": datetime(2026, 5, 5),  # Rate-limiting requests — 30-day cooldown
}


# Companies discovered via LinkedIn that need direct ATS search.
_LINKEDIN_DISCOVERED_COMPANIES: set[str] = set()


def get_and_clear_linkedin_companies() -> set[str]:
    """Return companies found via LinkedIn and clear the buffer."""
    companies = _LINKEDIN_DISCOVERED_COMPANIES.copy()
    _LINKEDIN_DISCOVERED_COMPANIES.clear()
    return companies


def _is_company_on_cooldown(company: str) -> bool:
    """Check if a company is on cooldown (rate-limited, etc.)."""
    key = company.strip().lower()
    unblock = COMPANY_COOLDOWNS.get(key)
    if unblock and datetime.now() < unblock:
        return True
    return False


# Jobs requiring US security clearance — non-starter for international
# student, no clearance possible). Exclude by title keywords and JD text.
# Companies whose external Greenhouse/Lever board is a decoy — they reject
# external applications and require re-applying via an internal employee portal.
# Instaply must not waste cycles on these.
BLOCKED_COMPANIES = frozenset({
    "intersystems",
    "gopuff",          # delivery ops — not relevant, floods Lever queue
})


def _is_company_blocked(company: str) -> bool:
    return (company or "").strip().lower() in BLOCKED_COMPANIES


CLEARANCE_TITLE_KEYWORDS = (
    "ts/sci", "tssci", "top secret", "top-secret", "secret clearance",
    "security clearance", "active clearance", "clearance required",
    "polygraph", "poly ", "ci poly", "fsp ", "cjis", "public trust",
    "cleared ", "dod clearance", "govt clearance", "government clearance",
)
CLEARANCE_JD_KEYWORDS = (
    "ts/sci", "top secret", "active security clearance",
    "active secret clearance", "active top secret",
    "must possess a security clearance", "must hold a security clearance",
    "us citizenship required", "u.s. citizenship required",
    "ability to obtain a security clearance",
    "eligible for a security clearance", "ci polygraph", "full scope polygraph",
    "counterintelligence polygraph", "must be a us citizen",
)


def _has_clearance_requirement(title: str, jd_text: str | None) -> bool:
    t = (title or "").lower()
    if any(k in t for k in CLEARANCE_TITLE_KEYWORDS):
        return True
    jd = (jd_text or "").lower()
    if any(k in jd for k in CLEARANCE_JD_KEYWORDS):
        return True
    return False


def _reject_clearance_job(job_id: str, reason: str) -> None:
    try:
        with get_connection() as conn:
            conn.execute(
                "UPDATE jobs SET status='rejected' WHERE id=?",
                (job_id,),
            )
            conn.commit()
        log.info("Rejected job %s (%s)", job_id, reason)
    except Exception as exc:
        log.warning("Could not reject clearance job %s: %s", job_id, exc)


def _get_apply_candidates(
    *,
    min_score: float = 0.75,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return jobs with ``packet_generated`` status that are above the score
    threshold and have not been applied to yet.

    Clearance-required roles are filtered at both the SQL level (title) and
    in Python (JD text), with matches demoted to ``rejected`` so they do not
    reappear on the next cycle.
    """
    # Build SQL NOT LIKE clauses for title-level clearance filter.
    title_not_like = " AND ".join(
        f"LOWER(j.title) NOT LIKE '%' || ? || '%'" for _ in CLEARANCE_TITLE_KEYWORDS
    )
    params: list[Any] = [min_score]
    params.extend(CLEARANCE_TITLE_KEYWORDS)
    params.extend(sorted(BLOCKED_COMPANIES))
    params.append(limit * 3)  # Over-fetch so JD filter doesn't starve the cycle.
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT
                j.id,
                j.title,
                j.company,
                j.url,
                j.match_score,
                j.source,
                j.resume_version,
                j.cover_letter_version,
                j.visa_sponsorship_likely,
                j.jd_text
            FROM jobs j
            WHERE j.status = 'packet_generated'
              AND j.match_score >= ?
              AND j.url IS NOT NULL
              AND j.url != ''
              AND {title_not_like}
              AND LOWER(j.company) NOT IN ({",".join("?" * len(BLOCKED_COMPANIES))})
              AND NOT EXISTS (
                SELECT 1 FROM application_tracking t WHERE t.job_id = j.id
              )
              AND LOWER(j.url) NOT LIKE '%myworkdayjobs.com%'
              AND LOWER(j.url) NOT LIKE '%myworkday.com%'
            ORDER BY j.match_score DESC, j.visa_sponsorship_likely DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    # JD-level secondary filter: reject (persist) matches, return the rest.
    kept: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        if _has_clearance_requirement(d.get("title", ""), d.get("jd_text", "")):
            _reject_clearance_job(d["id"], f"clearance_required title={d.get('title','')[:60]}")
            continue
        d.pop("jd_text", None)
        kept.append(d)
        if len(kept) >= limit:
            break
    return kept


def _get_packet_files(resume_gen_id: str, cover_letter_gen_id: str) -> dict[str, str | None]:
    """Look up PDF and DOCX file paths from the generation tables."""
    result: dict[str, str | None] = {
        "resume_pdf": None,
        "resume_docx": None,
        "cover_letter_pdf": None,
        "cover_letter_docx": None,
    }
    with get_connection() as conn:
        if resume_gen_id:
            row = conn.execute(
                "SELECT pdf_path, docx_path FROM resume_generations WHERE id = ?",
                (resume_gen_id,),
            ).fetchone()
            if row:
                result["resume_pdf"] = row["pdf_path"] if row["pdf_path"] and Path(row["pdf_path"]).exists() else None
                result["resume_docx"] = row["docx_path"] if row["docx_path"] and Path(row["docx_path"]).exists() else None
        if cover_letter_gen_id:
            row = conn.execute(
                "SELECT pdf_path, docx_path FROM cover_letter_generations WHERE id = ?",
                (cover_letter_gen_id,),
            ).fetchone()
            if row:
                result["cover_letter_pdf"] = row["pdf_path"] if row["pdf_path"] and Path(row["pdf_path"]).exists() else None
                result["cover_letter_docx"] = row["docx_path"] if row["docx_path"] and Path(row["docx_path"]).exists() else None
    return result


async def auto_apply_batch(
    *,
    min_score: float | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Run auto-apply on eligible jobs.

    1. Finds ``packet_generated`` jobs above the score threshold.
    2. For each, looks up resume/cover-letter files.
    3. Runs ``autofill_and_submit`` via Playwright.
    4. On successful submission, marks the job as ``applied`` and creates
       a tracking record.

    Returns a summary dict with counts and per-job results.
    """
    effective_min_score = min_score if min_score is not None else settings.auto_apply_min_score
    effective_limit = limit if limit is not None else settings.auto_apply_max_per_cycle

    candidates = _get_apply_candidates(min_score=effective_min_score, limit=effective_limit)
    if not candidates:
        return {
            "applied_count": 0,
            "skipped_count": 0,
            "error_count": 0,
            "results": [],
            "message": "No eligible jobs to auto-apply.",
        }

    profile = load_profile()
    master_resume = load_master_resume()
    # Merge contact info from master resume into profile for autofill.
    contact = dict(master_resume.get("contact", {}))
    full_name = master_resume.get("name", "")
    if full_name:
        name_parts = full_name.strip().split(None, 1)
        contact.setdefault("first_name", name_parts[0] if name_parts else "")
        contact.setdefault("last_name", name_parts[1] if len(name_parts) > 1 else "")
    # Always use the JOB_APPLICATION_EMAIL for form submissions — this is
    # the email connected to job portal accounts and where security codes
    # are sent, which may differ from the resume contact email.
    if settings.job_application_email:
        contact["email"] = settings.job_application_email
    profile = {**profile, "contact": contact}
    results: list[dict[str, Any]] = []
    applied_count = 0
    skipped_count = 0
    error_count = 0

    for job in candidates:
        job_id = job["id"]
        job_url = job["url"]
        company = job.get("company", "")
        title = job.get("title", "")

        # Skip companies on cooldown (rate-limited, etc.)
        if _is_company_on_cooldown(company):
            log.info("Skipping %s at %s — company on cooldown until %s",
                     title, company, COMPANY_COOLDOWNS.get(company.strip().lower()))
            results.append({
                "job_id": job_id,
                "company": company,
                "title": title,
                "status": "skipped",
                "reason": "company_cooldown",
            })
            skipped_count += 1
            continue

        # Skip LinkedIn URLs — they require login, can't autofill.
        # Collect the company name so we can search their direct ATS instead.
        if "linkedin.com/" in job_url:
            log.info("Skipping %s at %s — LinkedIn URL requires login; queuing company for ATS search", title, company)
            _LINKEDIN_DISCOVERED_COMPANIES.add(company.strip())
            try:
                from backend.db.jobs_repository import transition_job_status
                transition_job_status(job_id, "rejected", reason="linkedin_url_no_direct_apply")
            except Exception:
                pass
            skipped_count += 1
            continue

        # --- Cheap pre-check for obviously dead Workday URLs ---
        # Saves ~12s per dead URL by avoiding Chrome launch.
        if "myworkdayjobs.com" in job_url:
            try:
                async with httpx.AsyncClient(
                    follow_redirects=True, timeout=12, headers={"User-Agent": "Mozilla/5.0"}
                ) as client:
                    resp = await client.get(job_url)
                    body_snippet = resp.text[:3000].lower() if resp.status_code == 200 else ""
                    is_dead = (
                        resp.status_code == 404
                        or "this position has been filled" in body_snippet
                        or "job has been removed" in body_snippet
                        or "no longer accepting applications" in body_snippet
                        or "page not found" in body_snippet
                        or ("doesn't exist" in body_snippet and "/search" in str(resp.url))
                    )
                    if is_dead:
                        log.info("Pre-check: Workday URL dead (%s %s) — skipping %s at %s",
                                 resp.status_code, str(resp.url)[:80], title, company)
                        try:
                            from backend.db.jobs_repository import transition_job_status
                            transition_job_status(job_id, "rejected", reason="auto_apply:expired_pre_check")
                        except Exception:
                            pass
                        results.append({
                            "job_id": job_id, "company": company, "title": title,
                            "status": "skipped", "reason": "expired_pre_check",
                        })
                        skipped_count += 1
                        continue
            except Exception as exc:
                log.debug("Pre-check failed for %s (proceeding to Chrome): %s", job_url[:80], exc)

        log.info("Auto-applying to %s at %s (%s) score=%.2f", title, company, job_url, job["match_score"])

        # Look up packet files.
        files = _get_packet_files(
            job.get("resume_version", ""),
            job.get("cover_letter_version", ""),
        )

        if not files["resume_pdf"] and not files["resume_docx"]:
            log.warning("No resume file found for job %s (%s at %s), skipping.", job_id, title, company)
            results.append({
                "job_id": job_id,
                "company": company,
                "title": title,
                "status": "skipped",
                "reason": "no_resume_file",
            })
            skipped_count += 1
            continue

        # Retry logic: attempt up to 2 times for transient failures.
        autofill_result = None
        max_attempts = 2
        for attempt in range(max_attempts):
            try:
                autofill_result = await autofill_and_submit(
                    job_url=job_url,
                    profile=profile,
                    resume_pdf_path=files["resume_pdf"],
                    cover_letter_pdf_path=files["cover_letter_pdf"],
                    resume_docx_path=files["resume_docx"],
                    cover_letter_docx_path=files["cover_letter_docx"],
                    prefer_docx=True,
                    company=company,
                    role=title,
                )
                break  # Success — exit retry loop.
            except Exception as exc:
                is_transient = any(kw in str(exc).lower() for kw in [
                    "timeout", "net::err", "navigation", "target closed",
                    "connection refused", "socket", "browser has been closed",
                ])
                if is_transient and attempt < max_attempts - 1:
                    log.warning("Transient error for %s at %s (attempt %d/%d): %s — retrying in 10s",
                                title, company, attempt + 1, max_attempts, exc)
                    import asyncio as _aio
                    await _aio.sleep(10)
                    continue
                log.exception("Auto-apply error for %s at %s", title, company)
                # Mark as rejected so it doesn't keep retrying
                try:
                    from backend.db.jobs_repository import transition_job_status
                    transition_job_status(job_id, "rejected", reason=f"autofill_error: {str(exc)[:100]}")
                    log.info("Marked %s at %s as rejected (autofill_error)", title, company)
                except Exception:
                    pass
                results.append({
                    "job_id": job_id,
                    "company": company,
                    "title": title,
                    "status": "error",
                    "error": str(exc),
                })
                error_count += 1
                break
        if autofill_result is None:
            continue

        if autofill_result.get("submitted"):
            # Mark job as applied in the jobs table.
            try:
                mark_job_applied(job_id)
            except Exception as exc:
                log.warning("Could not transition job %s to applied: %s", job_id, exc)

            # Create tracking record.
            tracking = track_application(
                job_id=job_id,
                applied_via="autofill",
                notes=f"Auto-applied via {autofill_result.get('platform_detected', 'unknown')} platform. "
                      f"Filled: {', '.join(autofill_result.get('filled_fields', []))}",
            )

            results.append({
                "job_id": job_id,
                "company": company,
                "title": title,
                "status": "applied",
                "platform": autofill_result.get("platform_detected"),
                "filled_fields": autofill_result.get("filled_fields", []),
                "screenshot": autofill_result.get("screenshot_path", ""),
                "post_submit_screenshot": autofill_result.get("post_submit_screenshot", ""),
                "tracking_id": tracking.get("id", ""),
            })
            applied_count += 1
            log.info("Successfully auto-applied to %s at %s", title, company)
        else:
            # Form had unknown questions or submit button not found.
            reason = "needs_review" if autofill_result.get("needs_review") else "submit_not_found"
            results.append({
                "job_id": job_id,
                "company": company,
                "title": title,
                "status": "skipped",
                "reason": reason,
                "needs_review": autofill_result.get("needs_review", []),
                "screenshot": autofill_result.get("screenshot_path", ""),
            })
            skipped_count += 1
            log.info("Skipped auto-apply for %s at %s: %s", title, company, reason)

            # Mark failing jobs as rejected so they don't retry forever.
            # Both submit_not_found and needs_review are non-recoverable —
            # the form has fields we can't fill (mandatory checkboxes, custom dropdowns).
            if reason in ("submit_not_found", "needs_review"):
                try:
                    from backend.db.jobs_repository import transition_job_status
                    transition_job_status(job_id, "rejected",
                                          reason=f"auto_apply:{reason}")
                    log.info("Marked %s as rejected (%s)", title, reason)
                except Exception as exc:
                    log.warning("Could not mark %s as rejected: %s", title, exc)

    return {
        "applied_count": applied_count,
        "skipped_count": skipped_count,
        "error_count": error_count,
        "results": results,
        "message": f"Auto-applied to {applied_count} jobs, skipped {skipped_count}, errors {error_count}.",
    }


def run_auto_apply_sync(
    *,
    min_score: float | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Synchronous wrapper for ``auto_apply_batch`` (for use in threads)."""
    return asyncio.run(auto_apply_batch(min_score=min_score, limit=limit))
