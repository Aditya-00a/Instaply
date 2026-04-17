"""Real-time job search via JobSpy.

JobSpy scrapes Indeed, LinkedIn, ZipRecruiter, Glassdoor, Google,
and Bayt directly — returning real direct apply URLs (not aggregator
redirects). No API keys, no project mismatches, no bot detection
issues for our submitter (URLs are real ATS pages).

Flow:
  1. User searches → API runs jobspy → returns real-time results
  2. User clicks Apply → API upserts that one job into our jobs table
     and creates an applications row (so the submitter can pick it up)
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from typing import Any

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


@router.get("/jobs/search-live")
async def search_live(
    request: Request,
    q: str = "",
    where: str = "",
    remote: bool = False,
    user_id: str = Depends(current_user_id),
    _rl: None = rate_limit("jobs_search_live", per_min=20),
):
    """Real-time job search across Indeed, LinkedIn, ZipRecruiter, Google."""
    if not q.strip():
        return {"results": [], "count": 0, "source": "jobspy"}

    try:
        # Run blocking JobSpy in a thread (it does HTTP under the hood)
        results = await asyncio.to_thread(_scrape_jobs_sync, q.strip(), where.strip(), remote)
    except Exception as e:
        log.error("Search failed: %s", e)
        raise HTTPException(502, f"Job search failed: {str(e)[:100]}")

    return {
        "results": results,
        "count": len(results),
        "source": "jobspy",
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
