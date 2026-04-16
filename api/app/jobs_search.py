"""Real-time job search via Adzuna API.

Adzuna provides 8M+ jobs across all industries from major US job boards.
Free tier: ~250 calls/month for unverified, 1000+ for verified.

Flow:
  1. User searches → API hits Adzuna → returns live results (not stored)
  2. User clicks Apply → API upserts that one job into our jobs table
     and creates an applications row (so the submitter can pick it up)
"""
from __future__ import annotations

import logging
import re
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from .auth import current_user_id
from .config import settings
from .db import service_client
from .ratelimit import rate_limit

log = logging.getLogger("jobs_search")

router = APIRouter(tags=["jobs"])


def _slug(name: str) -> str:
    """Make a URL-safe slug from company name."""
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "unknown"


@router.get("/jobs/search-live")
async def search_live(
    request: Request,
    q: str = "",
    where: str = "",
    remote: bool = False,
    page: int = 1,
    user_id: str = Depends(current_user_id),
    _rl: None = rate_limit("jobs_search_live", per_min=30),
):
    """Real-time job search via Adzuna API."""
    if not q.strip():
        return {"results": [], "count": 0, "source": "adzuna"}

    if not settings.adzuna_app_id or not settings.adzuna_app_key:
        raise HTTPException(500, "Adzuna API not configured")

    params: dict[str, Any] = {
        "app_id": settings.adzuna_app_id,
        "app_key": settings.adzuna_app_key,
        "what": q.strip(),
        "results_per_page": 20,
        "content-type": "application/json",
    }
    if where.strip():
        params["where"] = where.strip()
    if remote:
        params["title_only"] = "remote"

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"https://api.adzuna.com/v1/api/jobs/us/search/{page}",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        log.error("Adzuna search failed: %s", e)
        raise HTTPException(502, "Job search service unavailable")

    # Normalize Adzuna results to our job shape
    results = []
    for r in data.get("results", []):
        company_name = (r.get("company") or {}).get("display_name") or "Unknown"
        location_name = (r.get("location") or {}).get("display_name") or ""
        category = (r.get("category") or {}).get("label") or ""
        salary_min = r.get("salary_min")
        salary_max = r.get("salary_max")
        salary_str = ""
        if salary_min and salary_max:
            salary_str = f"${int(salary_min):,} - ${int(salary_max):,}"
        elif salary_min:
            salary_str = f"${int(salary_min):,}+"

        results.append({
            "external_id": f"adzuna:{r.get('id')}",
            "title": r.get("title", ""),
            "company_name": company_name,
            "company_slug": _slug(company_name),
            "location": location_name,
            "remote": "remote" in location_name.lower(),
            "apply_url": r.get("redirect_url", ""),
            "description": (r.get("description") or "")[:500],
            "category": category,
            "salary": salary_str,
            "created": r.get("created", ""),
            "source": "adzuna",
        })

    return {
        "results": results,
        "count": data.get("count", 0),
        "source": "adzuna",
        "page": page,
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

    # Upsert the job into our jobs table
    job_payload = {
        "source": "adzuna",
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
