"""Auto-Apply discovery worker endpoint.

Triggered by a scheduled job (cron). For each user with auto_apply_enabled:
  1. Skip if paused (paused_until > now) or in quiet hours
  2. Skip if the daily queue cap is already hit
  3. Search JobSpy for each target_title × target_location
  4. Score each result against the user's resume
  5. Insert top matches directly into applications (status='queued')
  6. Worker picks them up independently → autofill → submit
  7. Rows that need human help settle into needs_review / failed without
     blocking the rest of the queue

Also exposes endpoints for the UI to:
  - Trigger a manual discovery run
  - Handle legacy approve/skip rows for backward compatibility only
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


def _score_job_against_skills(
    job_title: str,
    job_company: str,
    skills: dict[str, Any],
    job_description: str = "",
) -> int:
    """Resume-to-job match scoring. Uses title + full description.

    Weights:
      - 40% Skills overlap with description (Python, SQL, Excel, etc.)
      - 25% Title alignment with held titles + target titles
      - 15% Industry match (description mentions user's industries)
      - 10% Experience-level match (entry/mid/senior implied)
      - 10% Education match (degree, major in description)
    """
    title = (job_title or "").lower()
    company = (job_company or "").lower()
    desc = (job_description or "").lower()
    haystack = f"{title} {desc} {company}"  # what we search against
    score = 0.0
    factors = 0.0

    # 1. SKILLS MATCH (40%) — count user skills mentioned in description
    user_skills = [s.lower() for s in (skills.get("skills") or [])]
    if user_skills:
        matched = 0
        for skill in user_skills:
            # Exact phrase match in description (e.g. "machine learning")
            if skill in haystack:
                matched += 1
        # Cap at 10 to avoid penalty for short skill lists
        ratio = min(matched / min(len(user_skills), 10), 1.0)
        score += 0.4 * ratio
        factors += 0.4

    # 2. TITLE ALIGNMENT (25%) — held titles vs job title
    held_titles = [t.lower() for t in (skills.get("titles_held") or [])]
    if held_titles:
        best = 0.0
        for held in held_titles:
            words = [w for w in held.split() if len(w) > 2]
            if not words:
                continue
            matched_w = sum(1 for w in words if w in title)
            ratio = matched_w / len(words)
            best = max(best, ratio)
        score += 0.25 * best
        factors += 0.25

    # 3. INDUSTRY MATCH (15%) — user's industries vs job
    industries = [i.lower() for i in (skills.get("industries") or [])]
    if industries:
        match = any(ind in haystack for ind in industries)
        score += 0.15 if match else 0
        factors += 0.15

    # 4. EXPERIENCE LEVEL (10%) — entry/mid/senior alignment
    exp_years = skills.get("experience_years") or 0
    seniority_pref = (skills.get("_seniority_pref") or "any").lower()
    is_senior_job = any(w in title for w in ("senior", "staff", "principal", "lead", "iii", "iv", "manager", "director", "head"))
    is_staff_plus_job = any(w in title for w in ("staff", "principal", "director", "head", "vp"))
    is_entry_job = any(w in title for w in ("junior", "entry", "associate", "intern", "graduate", "trainee", " i ", " ii"))
    is_mid_job = not is_senior_job and not is_entry_job

    if exp_years:
        # Match: senior people for senior jobs; entry people for entry jobs
        if exp_years >= 5 and is_senior_job:
            score += 0.10
        elif exp_years <= 2 and is_entry_job:
            score += 0.10
        elif 3 <= exp_years < 5 and is_mid_job:
            score += 0.10
        elif is_mid_job:
            score += 0.05  # neutral title, partial credit
        factors += 0.10

    # User's explicit seniority preference: hard penalty for mismatches.
    # This dominates inferred experience-level matching above.
    if seniority_pref != "any":
        wants_entry = seniority_pref == "entry"
        wants_mid = seniority_pref == "mid"
        wants_senior = seniority_pref == "senior"
        wants_staff_plus = seniority_pref == "staff_plus"

        mismatch = (
            (wants_entry and is_senior_job)
            or (wants_mid and (is_senior_job or is_entry_job))
            or (wants_senior and not (is_senior_job or is_staff_plus_job))
            or (wants_senior and is_entry_job)
            or (wants_staff_plus and not is_staff_plus_job)
        )
        match_pref = (
            (wants_entry and is_entry_job)
            or (wants_mid and is_mid_job)
            or (wants_senior and is_senior_job and not is_staff_plus_job)
            or (wants_staff_plus and is_staff_plus_job)
        )
        if mismatch:
            score -= 0.20
        elif match_pref:
            score += 0.10

    # 5. EDUCATION RELEVANCE (10%) — degree/major mentioned in desc
    education = skills.get("education") or {}
    if education:
        major = (education.get("major") or "").lower()
        if major and major in haystack:
            score += 0.10
        elif major:
            # Partial credit if any major-word appears
            major_words = [w for w in major.split() if len(w) > 3]
            if major_words and any(w in haystack for w in major_words):
                score += 0.05
        factors += 0.10

    if factors <= 0:
        return 0
    return max(0, min(100, round((score / factors) * 100)))


# ─── LLM-based match analysis (Cerebras) ─────────────────────────

async def _llm_match_score(
    job_title: str,
    job_description: str,
    job_company: str,
    skills: dict[str, Any],
) -> int | None:
    """Call Cerebras to compute a match score 0-100. Used only for top candidates
    to avoid burning the free tier."""
    import os
    import httpx
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("CEREBRAS_API_KEY", "")
    if not api_key or not job_description:
        return None

    summary = skills.get("summary", "")[:500]
    user_skills = ", ".join((skills.get("skills") or [])[:15])
    user_titles = ", ".join((skills.get("titles_held") or [])[:5])
    exp = skills.get("experience_years", 0)

    prompt = f"""Rate how well this candidate matches this job from 0 to 100.

CANDIDATE:
Skills: {user_skills}
Titles held: {user_titles}
Years of experience: {exp}
Summary: {summary}

JOB:
Title: {job_title}
Company: {job_company}
Description: {job_description[:1500]}

Return ONLY a number 0-100. No explanation. Just the number."""

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.cerebras.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    # Cerebras only entitles `llama3.1-8b` and
                    # `qwen-3-235b-a22b-instruct-2507` on this account
                    # (same constraint that bit resume_analyzer.py on
                    # 2026-04-19). 8B is plenty for a 0–100 numeric
                    # score and ~10× faster than the 235B Qwen for top-5
                    # parallel calls. Falls back to heuristic if even
                    # this 404s.
                    "model": "llama3.1-8b",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 8,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()
            # Extract first number
            m = re.search(r"\d+", content)
            if m:
                n = int(m.group())
                return max(0, min(100, n))
    except Exception as e:
        log.warning("LLM match failed: %s", e)
    return None


async def _scrape_for_targets_multi(
    titles: list[str],
    locations: list[str],
    keywords: list[str] | None = None,
    skills: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Aggregate jobs from all sources for each title × location.

    Build a list of search queries:
      - Each title alone
      - Each title + each keyword (if keywords set)
      - Top job titles the user has held (from resume)
    Capped at 10 total queries to bound work.
    """
    from .jobs_search import _search_themuse, _search_arbeitnow, _scrape_jobs_sync

    keywords = keywords or []
    skills = skills or {}
    held_titles: list[str] = (skills.get("titles_held") or [])[:3]

    queries: list[str] = []
    for title in titles[:5]:
        queries.append(title)
        for kw in keywords[:3]:
            queries.append(f"{title} {kw}")
    # Add resume-based titles the user has actually held — they're often
    # the strongest signal of what they're qualified for
    for ht in held_titles:
        if ht not in queries:
            queries.append(ht)
    # If user has keywords but no titles, still let them search by keyword alone
    if not titles:
        for kw in keywords[:5]:
            queries.append(kw)
    # Dedup and cap
    seen_q = set()
    deduped: list[str] = []
    for q in queries:
        ql = q.lower().strip()
        if ql and ql not in seen_q:
            seen_q.add(ql)
            deduped.append(q)
    queries = deduped[:10]
    log.info("Discovery queries: %s", queries)

    seen: set[str] = set()
    out: list[dict[str, Any]] = []

    for query in queries:
        loc = locations[0] if locations else "United States"
        tasks = [
            asyncio.to_thread(_scrape_jobs_sync, query, loc, False),
            _search_themuse(query, loc),
            _search_arbeitnow(query),
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

    # Belt + suspenders: also gate the UPDATE by user_id, in case another
    # session/user races between the SELECT above and this UPDATE.
    db.table("pending_approval").update({
        "status": decision,
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", pending_id).eq("user_id", user_id).execute()

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
    skills["_seniority_pref"] = prefs.data.get("seniority") or "any"

    min_score = prefs.data.get("auto_apply_min_match", 70)
    keywords = prefs.data.get("auto_apply_keywords") or []
    daily_cap = int(prefs.data.get("auto_apply_daily_cap") or 5)

    # Try discovery — if nothing found, try again with relaxed criteria
    inserted = await _discover_for_user(db, user_id, titles, locations, skills, min_score, keywords, daily_cap=daily_cap)
    if inserted == 0 and min_score > 50:
        log.info("First pass found 0 jobs for %s -- relaxing min_score to 50", user_id[:8])
        inserted = await _discover_for_user(db, user_id, titles, locations, skills, 50, keywords, daily_cap=daily_cap)
    if inserted == 0:
        log.info("Second pass found 0 jobs for %s -- searching with no location filter", user_id[:8])
        inserted = await _discover_for_user(db, user_id, titles, [], skills, 40, keywords, daily_cap=daily_cap)

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
    keywords: list[str] | None = None,
    daily_cap: int = 5,
) -> int:
    """Async helper: scrape, score, upsert jobs, queue applications.

    As of 2026-04-19 the user-approval middleware is removed. Matching
    jobs go straight into `applications` with `status='queued'` so the
    worker picks them up immediately. Dedupe is enforced by the
    existing UNIQUE (user_id, job_id) constraint on `applications`
    (migration 0001_init.sql:145). The daily cap is enforced inline by
    counting applications queued today against `daily_cap`.

    Credits remain safe: deduction happens via the
    `application_confirmed` Postgres trigger (migration 0006), which
    only fires when `confirmed_at` is set on a row — direct queue
    inserts do not consume credits.
    """
    jobs = await _scrape_for_targets_multi(titles, locations, keywords or [], skills)
    log.info("Discovered %d raw jobs for user %s", len(jobs), user_id[:8])
    if not jobs:
        return 0

    # If user has no extracted_skills, fall back to title-only matching:
    # any job whose title contains any target title word should pass.
    no_skills = not (skills.get("skills") or skills.get("titles_held"))

    # Score every job using DESCRIPTION (not just title)
    scored = []
    for job in jobs:
        s = _score_job_against_skills(
            job["title"], job["company_name"], skills,
            job_description=job.get("description", ""),
        )
        if no_skills:
            title_l = (job["title"] or "").lower()
            if any(any(w in title_l for w in t.lower().split()) for t in titles):
                s = max(s, 70)
        scored.append((s, job))

    # Sort by score desc, then run LLM verification on top 5 to refine
    scored.sort(key=lambda x: -x[0])
    if not no_skills and scored:
        log.info("Top 5 by title+desc heuristic: %s",
                 [(s, j["title"][:30]) for s, j in scored[:5]])
        # LLM-refine top candidates (parallel calls)
        top_jobs = [j for _, j in scored[:5] if j.get("description")]
        if top_jobs:
            llm_tasks = [_llm_match_score(j["title"], j["description"], j["company_name"], skills) for j in top_jobs]
            llm_scores = await asyncio.gather(*llm_tasks, return_exceptions=True)
            for i, llm_s in enumerate(llm_scores):
                if isinstance(llm_s, int) and llm_s is not None:
                    # Replace heuristic with LLM score (more accurate)
                    job = top_jobs[i]
                    for j, (orig_s, orig_j) in enumerate(scored):
                        if orig_j.get("external_id") == job.get("external_id"):
                            scored[j] = (llm_s, orig_j)
                            break
            scored.sort(key=lambda x: -x[0])
            log.info("After LLM: %s", [(s, j["title"][:30]) for s, j in scored[:5]])

    # Restrict to ATS hosts the agent can reliably submit on.
    # Greenhouse + Lever only — battle-tested, low-friction forms.
    # Workday is OFF: the multi-step forms ask too many custom questions
    # the bot can't answer (most stalled at needs_review with 5+ Qs per
    # form). Re-enable once the agent has a richer answer pool or we add
    # an LLM that can reason through novel screening questions.
    SUPPORTED_HOSTS = ("greenhouse.io", "lever.co")

    def is_supported(url: str) -> bool:
        return any(h in (url or "").lower() for h in SUPPORTED_HOSTS)

    # Daily cap budget. Count today's queued applications for this user
    # (any status — once queued, the row counts against the cap even if
    # the worker advances it to in_progress / submitted / failed before
    # the next discovery pass). This prevents a user from being spammed
    # with 50 applications a day if the cron drifts.
    today_iso = datetime.now(timezone.utc).date().isoformat() + "T00:00:00+00:00"
    try:
        already_today = (
            db.table("applications")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .gte("queued_at", today_iso)
            .execute()
        )
        already_count = already_today.count or 0
    except Exception:
        already_count = 0  # fail-open on a count error; insert dedup will still protect
    remaining_budget = max(0, daily_cap - already_count)

    inserted = 0
    for score, job in scored:
        if remaining_budget <= 0:
            break
        if score < min_score:
            continue
        if not is_supported(job.get("apply_url", "")):
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

        # Direct insert into applications with status='queued'. The user-
        # approval middleware is gone (2026-04-19) — matching jobs go
        # straight to the worker. Dedupe via UNIQUE (user_id, job_id);
        # the duplicate signal is the same shape as the old
        # pending_approval path, so log discipline is unchanged.
        try:
            db.table("applications").insert({
                "user_id": user_id,
                "job_id": job_id,
                "status": "queued",
                # match_score is 0-100 int; applications.fit_score is
                # 0-1 float per existing rows. Normalize.
                "fit_score": float(score) / 100.0,
            }).execute()
            inserted += 1
            remaining_budget -= 1
        except Exception as e:
            msg = str(e).lower()
            if "duplicate" in msg or "unique" in msg or "23505" in msg:
                continue  # already queued for this user — expected
            log.warning("applications insert failed for user=%s job=%s: %s",
                        user_id[:8], job_id[:8], e)

    return inserted


# ─── Cron-triggered endpoint (called by Fly/scheduler) ────────────

@router.post("/auto-apply/cron")
async def cron_run(request: Request):
    """Run discovery for ALL eligible users. Protected by a shared secret."""
    import hmac
    from .config import settings
    auth_header = request.headers.get("authorization", "")
    if not settings.cron_secret:
        raise HTTPException(401, "Bad cron secret")
    expected = f"Bearer {settings.cron_secret}"
    # Constant-time comparison to neutralize byte-by-byte timing attacks
    if not hmac.compare_digest(auth_header.encode(), expected.encode()):
        raise HTTPException(401, "Bad cron secret")

    db = service_client()
    eligible = (
        db.table("preferences")
        .select("user_id, target_titles, target_locations, auto_apply_keywords, auto_apply_min_match, "
                "auto_apply_quiet_start, auto_apply_quiet_end, auto_apply_paused_until, seniority")
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
        skills["_seniority_pref"] = pref.get("seniority") or "any"
        min_score = pref.get("auto_apply_min_match", 70)

        try:
            n = await _discover_for_user(
                db, user_id, titles,
                pref.get("target_locations") or [], skills, min_score,
                pref.get("auto_apply_keywords") or [],
                daily_cap=int(pref.get("auto_apply_daily_cap") or 5),
            )
            summary["found"] += n
            summary["ran"] += 1
            db.table("preferences").update({
                "auto_apply_last_run_at": now_iso,
            }).eq("user_id", user_id).execute()
        except Exception as e:
            log.error("Discovery failed for user %s: %s", user_id[:8], e)

    return summary
