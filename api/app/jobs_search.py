"""Real-time job search aggregating multiple free sources.

Sources (no API keys required):
  - JobSpy (Indeed, LinkedIn, ZipRecruiter, Google) - largest US coverage
  - Themuse - 90k+ jobs, all industries (healthcare, marketing, etc.)
  - Arbeitnow - 4M+ jobs worldwide
  - Remotive - remote tech jobs
  - Hacker News "Who's Hiring" - YC startups + tech

Each source runs in parallel. Results are deduped by URL hash.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from .auth import current_user_id
from .db import service_client
from .ratelimit import rate_limit

log = logging.getLogger("jobs_search")

router = APIRouter(tags=["jobs"])


def _slug(name: str) -> str:
    """Make a URL-safe slug from company name."""
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "unknown"


def _stable_id(url: str, fallback: str = "") -> str:
    """Generate a stable ID from a URL (so deduping works across searches)."""
    base = url or fallback
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


def _scrape_jobs_sync(query: str, location: str, remote: bool) -> list[dict[str, Any]]:
    """Run JobSpy synchronously. Called from threadpool to avoid blocking."""
    from jobspy import scrape_jobs

    kwargs: dict[str, Any] = {
        "site_name": ["indeed", "zip_recruiter", "google"],
        "search_term": query,
        "location": location or "United States",
        "results_wanted": 20,
        "hours_old": 168,  # last week
        "country_indeed": "USA",
        "verbose": 0,
    }
    if remote:
        kwargs["is_remote"] = True

    try:
        df = scrape_jobs(**kwargs)
    except Exception as e:
        log.error("JobSpy scrape failed: %s", e)
        raise

    if df is None or df.empty:
        return []

    results = []
    for _, row in df.iterrows():
        job_url = str(row.get("job_url", "") or "")
        title = str(row.get("title", "") or "")
        company = str(row.get("company", "") or "Unknown")
        loc = str(row.get("location", "") or "")
        site = str(row.get("site", "") or "unknown")

        if not job_url or not title:
            continue

        # Salary
        salary_str = ""
        smin = row.get("min_amount")
        smax = row.get("max_amount")
        if smin and smax:
            try:
                salary_str = f"${int(float(smin)):,} - ${int(float(smax)):,}"
            except (ValueError, TypeError):
                pass
        elif smin:
            try:
                salary_str = f"${int(float(smin)):,}+"
            except (ValueError, TypeError):
                pass

        results.append({
            "external_id": f"{site}:{_stable_id(job_url)}",
            "title": title,
            "company_name": company,
            "company_slug": _slug(company),
            "location": loc,
            "remote": bool(row.get("is_remote", False)),
            "apply_url": job_url,
            "description": str(row.get("description", "") or "")[:500],
            "category": "",
            "salary": salary_str,
            "source": site,
        })

    return results


async def _search_themuse(query: str, location: str) -> list[dict[str, Any]]:
    """Themuse public API — 90k+ jobs, all industries."""
    try:
        params = {"page": 1}
        # Themuse uses category filtering; we'll search by name in results
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://www.themuse.com/api/public/jobs",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        log.warning("Themuse failed: %s", e)
        return []

    q_lower = query.lower()
    loc_lower = location.lower()
    results = []
    for r in data.get("results", []):
        name = (r.get("name") or "").lower()
        if q_lower not in name:
            continue
        loc_list = r.get("locations") or []
        loc_name = loc_list[0].get("name", "") if loc_list else ""
        if loc_lower and loc_lower not in loc_name.lower():
            continue
        url = (r.get("refs") or {}).get("landing_page") or ""
        if not url:
            continue
        results.append({
            "external_id": f"themuse:{_stable_id(url)}",
            "title": r.get("name", ""),
            "company_name": (r.get("company") or {}).get("name", "Unknown"),
            "company_slug": _slug((r.get("company") or {}).get("name", "")),
            "location": loc_name,
            "remote": "remote" in loc_name.lower(),
            "apply_url": url,
            "description": "",
            "category": (r.get("categories") or [{}])[0].get("name", "") if r.get("categories") else "",
            "salary": "",
            "source": "themuse",
        })
    return results


async def _search_arbeitnow(query: str) -> list[dict[str, Any]]:
    """Arbeitnow public API — 4M+ jobs worldwide, no auth."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://www.arbeitnow.com/api/job-board-api",
                params={"search": query},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        log.warning("Arbeitnow failed: %s", e)
        return []

    results = []
    for j in data.get("data", [])[:25]:
        url = j.get("url", "")
        if not url:
            continue
        loc = j.get("location", "")
        results.append({
            "external_id": f"arbeitnow:{_stable_id(url)}",
            "title": j.get("title", ""),
            "company_name": j.get("company_name", "Unknown"),
            "company_slug": _slug(j.get("company_name", "")),
            "location": loc,
            "remote": bool(j.get("remote", False)),
            "apply_url": url,
            "description": (j.get("description") or "")[:500],
            "category": "",
            "salary": "",
            "source": "arbeitnow",
        })
    return results


async def _search_remotive(query: str) -> list[dict[str, Any]]:
    """Remotive — remote tech jobs, no auth."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://remotive.com/api/remote-jobs",
                params={"search": query, "limit": 20},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        log.warning("Remotive failed: %s", e)
        return []

    results = []
    for j in data.get("jobs", [])[:20]:
        url = j.get("url", "")
        if not url:
            continue
        results.append({
            "external_id": f"remotive:{_stable_id(url)}",
            "title": j.get("title", ""),
            "company_name": j.get("company_name", "Unknown"),
            "company_slug": _slug(j.get("company_name", "")),
            "location": j.get("candidate_required_location", "Remote"),
            "remote": True,
            "apply_url": url,
            "description": (j.get("description") or "")[:500],
            "category": j.get("category", ""),
            "salary": j.get("salary", ""),
            "source": "remotive",
        })
    return results


@router.get("/jobs/search-live")
async def search_live(
    request: Request,
    q: str = "",
    where: str = "",
    remote: bool = False,
    user_id: str = Depends(current_user_id),
    _rl: None = rate_limit("jobs_search_live", per_min=20),
):
    """Real-time job search aggregating multiple free sources in parallel."""
    if not q.strip():
        return {"results": [], "count": 0, "sources": []}

    query = q.strip()
    location = where.strip()

    # Run all sources in parallel
    tasks = [
        asyncio.to_thread(_scrape_jobs_sync, query, location, remote),
        _search_themuse(query, location),
        _search_arbeitnow(query),
    ]
    if remote or "remote" in query.lower():
        tasks.append(_search_remotive(query))

    results_per_source = await asyncio.gather(*tasks, return_exceptions=True)

    # Merge + dedup by external_id
    seen_ids: set[str] = set()
    all_results = []
    sources_used = []
    for r in results_per_source:
        if isinstance(r, Exception):
            log.warning("Source failed: %s", r)
            continue
        if not r:
            continue
        for job in r:
            ext_id = job.get("external_id", "")
            if ext_id in seen_ids:
                continue
            seen_ids.add(ext_id)
            all_results.append(job)
        if r:
            sources_used.append(r[0].get("source", "?"))

    # Apply remote filter if requested (post-merge)
    if remote:
        all_results = [j for j in all_results if j.get("remote")]

    return {
        "results": all_results,
        "count": len(all_results),
        "sources": list(set(sources_used)),
    }


@router.post("/applications/queue-live")
async def queue_live(
    request: Request,
    user_id: str = Depends(current_user_id),
    _rl: None = rate_limit("queue_live", per_min=30),
):
    """Queue an application for a live (non-DB) job from Adzuna.

    Upserts the job into our jobs table first, then creates the application.
    The submitter handles the rest as usual.
    """
    body = await request.json()
    required = ["external_id", "title", "company_name", "apply_url"]
    for k in required:
        if not body.get(k):
            raise HTTPException(400, f"{k} is required")

    db = service_client()

    # Source comes from JobSpy as 'indeed', 'linkedin', etc.
    # Default to 'manual' if unknown.
    source = body.get("source", "manual")
    valid_sources = {"greenhouse", "lever", "smartrecruiters", "workday",
                     "ashby", "icims", "adzuna", "manual",
                     "indeed", "linkedin", "zip_recruiter", "google", "glassdoor", "bayt"}
    if source not in valid_sources:
        source = "manual"

    # Upsert the job into our jobs table
    job_payload = {
        "source": source,
        "external_id": body["external_id"],
        "company_slug": body.get("company_slug") or _slug(body["company_name"]),
        "company_name": body["company_name"],
        "title": body["title"],
        "location": body.get("location") or None,
        "remote": bool(body.get("remote", False)),
        "apply_url": body["apply_url"],
        "is_active": True,
    }

    try:
        upsert_resp = (
            db.table("jobs")
            .upsert(job_payload, on_conflict="source,external_id")
            .execute()
        )
        if not upsert_resp.data:
            raise HTTPException(500, "Failed to save job")
        job_id = upsert_resp.data[0]["id"]
    except Exception as e:
        log.error("Job upsert failed: %s", e)
        raise HTTPException(500, "Could not save job")

    # Check if already applied
    existing = (
        db.table("applications")
        .select("id, status")
        .eq("user_id", user_id)
        .eq("job_id", job_id)
        .limit(1)
        .execute()
    )
    if existing.data:
        return {"ok": True, "already_applied": True, "application_id": existing.data[0]["id"]}

    # Create the application
    try:
        app_resp = db.table("applications").insert({
            "user_id": user_id,
            "job_id": job_id,
            "status": "queued",
        }).execute()
        return {"ok": True, "application_id": app_resp.data[0]["id"], "job_id": job_id}
    except Exception as e:
        log.error("Application insert failed: %s", e)
        raise HTTPException(500, "Could not queue application")
