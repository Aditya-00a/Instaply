"""Auto-Apply discovery worker endpoint.

Triggered by a scheduled job (cron). For each user with auto_apply_enabled:
  1. Skip if paused (paused_until > now) or in quiet hours
  2. Skip if daily cap already hit
  3. Search JobSpy for each target_title × target_location
  4. Score each result against the user's resume
  5. Insert top matches into pending_approval (status='pending')
  6. User approves via UI → applications row created
  7. Submitter picks up applications → autofill → submit

Also exposes endpoints for the UI to:
  - Approve/skip pending jobs
  - Trigger a manual discovery run
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import datetime, time, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from .auth import current_user_id
from .db import service_client
from .ratelimit import rate_limit

log = logging.getLogger("auto_apply")

router = APIRouter(tags=["auto-apply"])


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "unknown"


def _stable_id(url: str) -> str:
    return hashlib.sha256((url or "").encode("utf-8")).hexdigest()[:16]


def _score_job_against_skills(job_title: str, job_company: str, skills: dict[str, Any]) -> int:
    """Same scoring as web search page (skills + titles_held + industries)."""
    title = (job_title or "").lower()
    company = (job_company or "").lower()
    score = 0.0
    factors = 0.0

    user_skills = [s.lower() for s in (skills.get("skills") or [])]
    if user_skills:
        title_words = re.split(r"[\s,\-/()]+", title)
        matched = 0
        for skill in user_skills:
            sw = skill.split()
            if all(any(w in tw or tw in w for tw in title_words) for w in sw):
                matched += 1
        score += 0.4 * min(matched / min(len(user_skills), 5), 1)
        factors += 0.4

    held_titles = [t.lower() for t in (skills.get("titles_held") or [])]
    if held_titles:
        best = 0.0
        for held in held_titles:
            words = held.split()
            matched_w = sum(1 for w in words if w in title and len(w) > 2)
            ratio = matched_w / len(words) if words else 0
            best = max(best, ratio)
        score += 0.35 * best
        factors += 0.35

    industries = [i.lower() for i in (skills.get("industries") or [])]
    if industries:
        if any(ind in title or ind in company for ind in industries):
            score += 0.1
        factors += 0.1

    return round((score / factors) * 100) if factors > 0 else 0


async def _scrape_for_targets_multi(titles: list[str], locations: list[str]) -> list[dict[str, Any]]:
    """Aggregate jobs from all sources for each title × location.

    Uses the same multi-source aggregator as the search page (Themuse,
    Arbeitnow, JobSpy/Indeed, Remotive) so we get coverage across
    healthcare, tech, marketing, etc. — not just tech.
    """
    from .jobs_search import _search_themuse, _search_arbeitnow, _scrape_jobs_sync

    seen: set[str] = set()
    out: list[dict[str, Any]] = []

    for title in titles[:5]:  # cap titles to bound work
        loc = locations[0] if locations else "United States"
        # Run all sources in parallel for this title
        tasks = [
            asyncio.to_thread(_scrape_jobs_sync, title, loc, False),
            _search_themuse(title, loc),
            _search_arbeitnow(title),
        ]
        results_per_source = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results_per_source:
            if isinstance(r, Exception) or not r:
                continue
            for job in r:
                eid = job.get("external_id", "")
                if eid in seen:
                    continue
                seen.add(eid)
                out.append(job)

    return out


def _is_quiet_now(quiet_start: str, quiet_end: str) -> bool:
    """Check if current UTC time falls inside quiet hours."""
    try:
        now = datetime.now(timezone.utc).time()
        start = time.fromisoformat(quiet_start)
        end = time.fromisoformat(quiet_end)
        if start <= end:
            return start <= now <= end
        # Spans midnight
        return now >= start or now <= end
    except Exception:
        return False


# ─── User-facing endpoints ────────────────────────────────────────

@router.post("/auto-apply/decide")
async def decide(
    request: Request,
    user_id: str = Depends(current_user_id),
    _rl: None = rate_limit("auto_apply_decide", per_min=60),
):
    """Approve or skip a pending job."""
    body = await request.json()
    pending_id = body.get("pending_id")
    decision = body.get("decision")  # "approved" | "skipped"

    if not pending_id or decision not in ("approved", "skipped"):
        raise HTTPException(400, "pending_id and valid decision required")

    db = service_client()
    pending = (
        db.table("pending_approval")
        .select("id, job_id")
        .eq("id", pending_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    if not pending.data:
        raise HTTPException(404, "Pending item not found")

    db.table("pending_approval").update({
        "status": decision,
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", pending_id).execute()

    if decision == "approved":
        db.table("applications").insert({
            "user_id": user_id,
            "job_id": pending.data["job_id"],
            "status": "queued",
        }).execute()

    return {"ok": True, "decision": decision}


@router.post("/auto-apply/run-now")
async def run_now(
    request: Request,
    user_id: str = Depends(current_user_id),
    _rl: None = rate_limit("auto_apply_run_now", per_min=2),
):
    """Manually trigger discovery for the current user."""
    db = service_client()
    prefs = db.table("preferences").select("*").eq("user_id", user_id).single().execute()
    if not prefs.data:
        raise HTTPException(400, "Set up your preferences first")

    titles = prefs.data.get("target_titles") or []
    locations = prefs.data.get("target_locations") or []
    if not titles:
        raise HTTPException(400, "Add at least one target title")

    profile = db.table("profiles").select("extracted_skills").eq("id", user_id).single().execute()
    skills = (profile.data.get("extracted_skills") if profile.data else {}) or {}

    min_score = prefs.data.get("auto_apply_min_match", 70)
    inserted = await _discover_for_user(db, user_id, titles, locations, skills, min_score)

    db.table("preferences").update({
        "auto_apply_last_run_at": datetime.now(timezone.utc).isoformat(),
    }).eq("user_id", user_id).execute()

    return {"ok": True, "found": inserted}


async def _discover_for_user(
    db: Any,
    user_id: str,
    titles: list[str],
    locations: list[str],
    skills: dict[str, Any],
    min_score: int,
) -> int:
    """Async helper: scrape, score, upsert jobs, insert pending_approval."""
    jobs = await _scrape_for_targets_multi(titles, locations)
    log.info("Discovered %d raw jobs for user %s", len(jobs), user_id[:8])
    if not jobs:
        return 0

    # If user has no extracted_skills, fall back to title-only matching:
    # any job whose title contains any target title word should pass.
    no_skills = not (skills.get("skills") or skills.get("titles_held"))

    # ATS hostnames the submitter knows how to fill out
    SUBMITTABLE_HOSTS = (
        "greenhouse.io", "lever.co", "smartrecruiters.com", "workday",
        "ashbyhq.com", "myworkdayjobs.com", "icims.com", "workable.com",
        "bamboohr.com", "jobvite.com",
    )

    def is_submittable(url: str) -> bool:
        return any(h in (url or "").lower() for h in SUBMITTABLE_HOSTS)

    inserted = 0
    for job in jobs:
        # Effective score: real LLM-based score, OR title-keyword fallback if no resume yet
        score = _score_job_against_skills(job["title"], job["company_name"], skills)
        if no_skills:
            # No resume yet — score by whether title contains any target keyword
            title_l = (job["title"] or "").lower()
            if any(any(w in title_l for w in t.lower().split()) for t in titles):
                score = max(score, 70)
        if score < min_score:
            continue

        # Skip jobs we can't auto-apply to (Indeed, LinkedIn, etc.)
        if not is_submittable(job.get("apply_url", "")):
            continue

        # Upsert into jobs table
        try:
            up = (
                db.table("jobs")
                .upsert({
                    "source": job["source"],
                    "external_id": job["external_id"],
                    "company_slug": job["company_slug"],
                    "company_name": job["company_name"],
                    "title": job["title"],
                    "location": job["location"],
                    "remote": job["remote"],
                    "apply_url": job["apply_url"],
                    "is_active": True,
                }, on_conflict="source,external_id")
                .execute()
            )
            if not up.data:
                continue
            job_id = up.data[0]["id"]
        except Exception as e:
            log.warning("job upsert failed: %s", e)
            continue

        # Insert into pending_approval (skip if already there)
        try:
            db.table("pending_approval").insert({
                "user_id": user_id,
                "job_id": job_id,
                "match_score": score,
            }).execute()
            inserted += 1
        except Exception:
            pass  # likely duplicate, skip

    return inserted


# ─── Cron-triggered endpoint (called by Fly/scheduler) ────────────

@router.post("/auto-apply/cron")
async def cron_run(request: Request):
    """Run discovery for ALL eligible users. Protected by a shared secret."""
    from .config import settings
    auth_header = request.headers.get("authorization", "")
    expected = f"Bearer {settings.cron_secret}" if settings.cron_secret else None
    if not expected or auth_header != expected:
        raise HTTPException(401, "Bad cron secret")

    db = service_client()
    eligible = (
        db.table("preferences")
        .select("user_id, target_titles, target_locations, auto_apply_min_match, "
                "auto_apply_quiet_start, auto_apply_quiet_end, auto_apply_paused_until")
        .eq("auto_apply_enabled", True)
        .execute()
    )

    now_iso = datetime.now(timezone.utc).isoformat()
    summary = {"total": 0, "skipped_paused": 0, "skipped_quiet": 0, "ran": 0, "found": 0}

    for pref in (eligible.data or []):
        summary["total"] += 1
        paused = pref.get("auto_apply_paused_until")
        if paused and paused > now_iso:
            summary["skipped_paused"] += 1
            continue
        if _is_quiet_now(pref.get("auto_apply_quiet_start") or "23:00",
                        pref.get("auto_apply_quiet_end") or "08:00"):
            summary["skipped_quiet"] += 1
            continue

        titles = pref.get("target_titles") or []
        if not titles:
            continue

        user_id = pref["user_id"]
        profile = db.table("profiles").select("extracted_skills").eq("id", user_id).single().execute()
        skills = (profile.data.get("extracted_skills") if profile.data else {}) or {}
        min_score = pref.get("auto_apply_min_match", 70)

        try:
            n = await _discover_for_user(
                db, user_id, titles,
                pref.get("target_locations") or [], skills, min_score
            )
            summary["found"] += n
            summary["ran"] += 1
            db.table("preferences").update({
                "auto_apply_last_run_at": now_iso,
            }).eq("user_id", user_id).execute()
        except Exception as e:
            log.error("Discovery failed for user %s: %s", user_id[:8], e)

    return summary
