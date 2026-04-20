"""Local job search + profile-derived query generation for Instaply MCP."""
from __future__ import annotations

import asyncio
import hashlib
import re
from collections import Counter
from typing import Any

import httpx

from . import db


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "unknown"


def _stable_id(url: str, fallback: str = "") -> str:
    base = url or fallback
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


def _profile_queries(profile: dict[str, Any]) -> list[str]:
    extracted = profile.get("extracted_skills") or {}
    role_targets = extracted.get("role_targets") or []
    titles_held = extracted.get("titles_held") or []
    preferred_titles = profile.get("preferred_titles") or []

    queries: list[str] = []
    for value in preferred_titles + role_targets + ([profile.get("current_title")] if profile.get("current_title") else []) + titles_held:
        if not value:
            continue
        cleaned = re.sub(r"\s+", " ", str(value)).strip()
        if cleaned and cleaned not in queries:
            queries.append(cleaned)

    if not queries:
        major = (profile.get("major") or "").lower()
        skills = {str(s).lower() for s in extracted.get("skills") or []}
        if {"python", "sql"} <= skills:
            queries.append("Data Analyst")
        elif "analytics" in major or "data" in major:
            queries.append("Data Analyst")
        elif "computer science" in major or "software" in major:
            queries.append("Software Engineer")

    return queries[:4]


def _profile_keywords(profile: dict[str, Any]) -> set[str]:
    extracted = profile.get("extracted_skills") or {}
    tokens: set[str] = set()
    for raw in (extracted.get("skills") or []) + (extracted.get("titles_held") or []):
        for token in re.findall(r"[a-z0-9]{3,}", str(raw).lower()):
            tokens.add(token)
    for raw in (profile.get("major"), profile.get("current_title"), profile.get("school")):
        for token in re.findall(r"[a-z0-9]{3,}", str(raw or "").lower()):
            tokens.add(token)
    return tokens


def _score_job(job: dict[str, Any], queries: list[str], keywords: set[str], preferred_location: str, remote: bool) -> tuple[float, list[str]]:
    title = str(job.get("title") or "")
    company = str(job.get("company_name") or "")
    location = str(job.get("location") or "")
    blob = " ".join(
        [
            title.lower(),
            company.lower(),
            location.lower(),
            str(job.get("description") or "").lower(),
        ]
    )

    score = 0.0
    reasons: list[str] = []

    for query in queries:
        q = query.lower()
        if q in title.lower():
            score += 0.55
            reasons.append(f"title matches '{query}'")
            break
        query_tokens = {tok for tok in re.findall(r"[a-z0-9]{3,}", q)}
        title_tokens = {tok for tok in re.findall(r"[a-z0-9]{3,}", title.lower())}
        if query_tokens and len(query_tokens & title_tokens) >= max(1, len(query_tokens) - 1):
            score += 0.35
            reasons.append(f"title overlaps '{query}'")
            break

    keyword_hits = [kw for kw in keywords if kw in blob]
    if keyword_hits:
        score += min(0.30, 0.05 * len(keyword_hits))
        reasons.append("matches resume/profile keywords: " + ", ".join(sorted(keyword_hits)[:4]))

    if remote and job.get("remote"):
        score += 0.10
        reasons.append("remote")
    elif preferred_location and preferred_location.lower() in location.lower():
        score += 0.08
        reasons.append("location match")

    return round(score, 3), reasons


def _search_jobspy_sync(query: str, location: str, remote: bool, limit: int) -> list[dict[str, Any]]:
    try:
        from jobspy import scrape_jobs
    except ImportError:
        return []

    kwargs: dict[str, Any] = {
        "site_name": ["indeed", "zip_recruiter", "google"],
        "search_term": query,
        "location": location or "United States",
        "results_wanted": limit,
        "hours_old": 168,
        "country_indeed": "USA",
        "verbose": 0,
    }
    if remote:
        kwargs["is_remote"] = True

    df = scrape_jobs(**kwargs)
    if df is None or df.empty:
        return []

    results: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        direct_url = str(row.get("job_url_direct", "") or "")
        job_url = direct_url if direct_url else str(row.get("job_url", "") or "")
        title = str(row.get("title", "") or "")
        company = str(row.get("company", "") or "Unknown")
        loc = str(row.get("location", "") or "")
        site = str(row.get("site", "") or "unknown")
        if direct_url:
            url_lower = direct_url.lower()
            if "greenhouse" in url_lower:
                site = "greenhouse"
            elif "lever.co" in url_lower:
                site = "lever"
            elif "smartrecruiters" in url_lower:
                site = "smartrecruiters"
            elif "workday" in url_lower or "myworkdayjobs" in url_lower:
                site = "workday"

        if not job_url or not title:
            continue

        results.append(
            {
                "external_id": f"{site}:{_stable_id(job_url)}",
                "title": title,
                "company_name": company,
                "company_slug": _slug(company),
                "location": loc,
                "remote": bool(row.get("is_remote", False)),
                "apply_url": job_url,
                "description": str(row.get("description", "") or "")[:800],
                "source": site,
            }
        )
    return results


async def _search_themuse(query: str, location: str) -> list[dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.get("https://www.themuse.com/api/public/jobs", params={"page": 1})
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return []

    q_lower = query.lower()
    loc_lower = location.lower()
    results: list[dict[str, Any]] = []
    for item in data.get("results", []):
        name = str(item.get("name") or "")
        if q_lower not in name.lower():
            continue
        loc_list = item.get("locations") or []
        loc_name = loc_list[0].get("name", "") if loc_list else ""
        if loc_lower and loc_lower not in loc_name.lower():
            continue
        url = (item.get("refs") or {}).get("landing_page") or ""
        if not url:
            continue
        raw_desc = item.get("contents") or item.get("description") or ""
        desc = re.sub(r"<[^>]+>", " ", raw_desc)
        desc = re.sub(r"\s+", " ", desc).strip()[:800]
        company = (item.get("company") or {}).get("name", "Unknown")
        results.append(
            {
                "external_id": f"themuse:{_stable_id(url)}",
                "title": name,
                "company_name": company,
                "company_slug": _slug(company),
                "location": loc_name,
                "remote": "remote" in loc_name.lower(),
                "apply_url": url,
                "description": desc,
                "source": "themuse",
            }
        )
    return results


async def _search_arbeitnow(query: str) -> list[dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.get("https://www.arbeitnow.com/api/job-board-api", params={"search": query})
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return []

    results: list[dict[str, Any]] = []
    for item in data.get("data", [])[:25]:
        url = item.get("url", "")
        if not url:
            continue
        company = item.get("company_name", "Unknown")
        results.append(
            {
                "external_id": f"arbeitnow:{_stable_id(url)}",
                "title": item.get("title", ""),
                "company_name": company,
                "company_slug": _slug(company),
                "location": item.get("location", ""),
                "remote": bool(item.get("remote", False)),
                "apply_url": url,
                "description": str(item.get("description") or "")[:800],
                "source": "arbeitnow",
            }
        )
    return results


async def _search_remotive(query: str) -> list[dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.get("https://remotive.com/api/remote-jobs", params={"search": query, "limit": 20})
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return []

    results: list[dict[str, Any]] = []
    for item in data.get("jobs", [])[:20]:
        url = item.get("url", "")
        if not url:
            continue
        company = item.get("company_name", "Unknown")
        results.append(
            {
                "external_id": f"remotive:{_stable_id(url)}",
                "title": item.get("title", ""),
                "company_name": company,
                "company_slug": _slug(company),
                "location": item.get("candidate_required_location", "Remote"),
                "remote": True,
                "apply_url": url,
                "description": str(item.get("description") or "")[:800],
                "source": "remotive",
            }
        )
    return results


async def search_jobs(
    *,
    query: str | None = None,
    location: str | None = None,
    remote: bool = False,
    limit: int = 20,
) -> dict[str, Any]:
    profile = db.get_profile()
    queries = [query.strip()] if query and query.strip() else _profile_queries(profile)
    if not queries:
        raise ValueError(
            "No search query provided and not enough profile/resume data to derive one. "
            "Import a resume first or pass query explicitly."
        )

    preferred_location = location or ", ".join(
        [part for part in [profile.get("city"), profile.get("state"), profile.get("country")] if part]
    )
    keywords = _profile_keywords(profile)

    tasks: list[Any] = []
    for q in queries[:4]:
        tasks.append(asyncio.to_thread(_search_jobspy_sync, q, preferred_location, remote, max(limit, 20)))
        tasks.append(_search_themuse(q, preferred_location))
        tasks.append(_search_arbeitnow(q))
        if remote or "remote" in q.lower():
            tasks.append(_search_remotive(q))

    gathered = await asyncio.gather(*tasks, return_exceptions=True)

    deduped: dict[str, dict[str, Any]] = {}
    source_counter: Counter[str] = Counter()
    for block in gathered:
        if isinstance(block, Exception) or not block:
            continue
        for job in block:
            key = str(job.get("apply_url") or job.get("external_id") or "")
            if not key or key in deduped:
                continue
            deduped[key] = job
            source_counter[str(job.get("source") or "unknown")] += 1

    scored: list[dict[str, Any]] = []
    for job in deduped.values():
        score, reasons = _score_job(job, queries, keywords, preferred_location, remote)
        row = dict(job)
        row["match_score"] = score
        row["match_reasons"] = reasons
        row["job_id"] = db.upsert_job(
            source=str(row.get("source") or "manual"),
            external_id=str(row.get("external_id") or _stable_id(str(row.get("apply_url") or ""))),
            company_name=str(row.get("company_name") or "Unknown"),
            title=str(row.get("title") or ""),
            apply_url=str(row.get("apply_url") or ""),
            location=str(row.get("location") or "") or None,
            description=str(row.get("description") or "") or None,
        )
        scored.append(row)

    scored.sort(
        key=lambda row: (
            float(row.get("match_score") or 0.0),
            1 if row.get("source") in {"greenhouse", "lever", "smartrecruiters"} else 0,
        ),
        reverse=True,
    )

    return {
        "ok": True,
        "derived_queries": queries,
        "location": preferred_location or "",
        "remote": remote,
        "sources": sorted(source_counter.keys()),
        "count": len(scored[:limit]),
        "results": scored[:limit],
    }
