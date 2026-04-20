from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from backend.db.database import get_connection
from backend.services.config import settings


ATS_HOST_PATTERNS: dict[str, tuple[str, ...]] = {
    "greenhouse": ("boards.greenhouse.io", "job-boards.greenhouse.io"),
    "lever": ("jobs.lever.co",),
    "workday": ("myworkdayjobs.com", "workdayjobs.com"),
    "ashby": ("jobs.ashbyhq.com",),
    "smartrecruiters": ("jobs.smartrecruiters.com", "careers.smartrecruiters.com"),
    "icims": ("icims.com/jobs/", "icims.com/careers-home/jobs", "social.icims.com/job/"),
    "jobvite": ("jobs.jobvite.com",),
    "taleo": ("taleo.net", "oraclecloud.com"),
    "bamboohr": ("bamboohr.com/careers",),
}
SUPPORTED_ATS_PROVIDERS = {"greenhouse", "lever", "workday", "ashby", "smartrecruiters", "icims", "jobvite", "taleo"}
CAREER_LINK_HINTS = ("career", "careers", "job", "jobs", "join-us", "join", "opportunity", "opportunities")
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
LINK_PATTERN = re.compile(r"""href\s*=\s*["']([^"'#]+)["']""", re.I)
TEXT_LINK_PATTERN = re.compile(r""">\s*([^<]{0,120})<""")
LOCALE_SEGMENT_PATTERN = re.compile(r"^[a-z]{2}(?:-[A-Z]{2})?$")


async def _request_with_retries(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = await client.request(method, url, **kwargs)
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                await asyncio.sleep(0.8 * (attempt + 1))
                continue
            return response
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = exc
            if attempt >= 2:
                raise
            await asyncio.sleep(0.8 * (attempt + 1))
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Request failed without response for {url}")

STATIC_DISCOVERY_SEEDS: dict[str, list[dict[str, str]]] = {
    "anthropic": [{"ats_provider": "greenhouse", "ats_target": "anthropic", "careers_url": "https://www.anthropic.com/careers"}],
    "openai": [{"ats_provider": "ashby", "ats_target": "https://jobs.ashbyhq.com/openai", "careers_url": "https://openai.com/careers/"}],
    "notion": [{"ats_provider": "greenhouse", "ats_target": "notion", "careers_url": "https://www.notion.so/careers"}],
    "figma": [{"ats_provider": "greenhouse", "ats_target": "figma", "careers_url": "https://www.figma.com/careers/"}],
    "cohere": [{"ats_provider": "greenhouse", "ats_target": "cohere", "careers_url": "https://cohere.com/careers"}],
    "scale ai": [{"ats_provider": "lever", "ats_target": "scaleai", "careers_url": "https://scale.com/careers"}],
    "scaleai": [{"ats_provider": "lever", "ats_target": "scaleai", "careers_url": "https://scale.com/careers"}],
    "runway": [{"ats_provider": "lever", "ats_target": "runway", "careers_url": "https://runwayml.com/careers/"}],
    "perplexity": [{"ats_provider": "lever", "ats_target": "perplexity", "careers_url": "https://www.perplexity.ai/careers"}],
    "monday.com": [{"ats_provider": "greenhouse", "ats_target": "monday", "careers_url": "https://monday.com/careers"}],
    "monday": [{"ats_provider": "greenhouse", "ats_target": "monday", "careers_url": "https://monday.com/careers"}],
    "databricks": [{"ats_provider": "lever", "ats_target": "databricks", "careers_url": "https://www.databricks.com/company/careers"}],
    "ramp": [{"ats_provider": "ashby", "ats_target": "https://jobs.ashbyhq.com/ramp", "careers_url": "https://ramp.com/careers"}],
    "rippling": [{"ats_provider": "greenhouse", "ats_target": "rippling", "careers_url": "https://www.rippling.com/careers"}],
    "plaid": [{"ats_provider": "greenhouse", "ats_target": "plaid", "careers_url": "https://plaid.com/careers/"}],
    "hubspot": [{"ats_provider": "greenhouse", "ats_target": "hubspot", "careers_url": "https://www.hubspot.com/careers"}],
    "snowflake": [{"ats_provider": "greenhouse", "ats_target": "snowflake", "careers_url": "https://careers.snowflake.com/"}],
    "airbnb": [{"ats_provider": "greenhouse", "ats_target": "airbnb", "careers_url": "https://careers.airbnb.com/"}],
    "servicenow": [{"ats_provider": "smartrecruiters", "ats_target": "https://careers.smartrecruiters.com/ServiceNow", "careers_url": "https://careers.smartrecruiters.com/ServiceNow"}],
    "nutanix": [{"ats_provider": "jobvite", "ats_target": "https://jobs.jobvite.com/nutanix", "careers_url": "https://jobs.jobvite.com/nutanix"}],
    "netflix": [
        {
            "ats_provider": "workday",
            "ats_target": "https://netflix.wd1.myworkdayjobs.com/wday/cxs/netflix/Netflix/jobs",
            "careers_url": "https://jobs.netflix.com/",
        }
    ],
}


def normalize_company_name(value: str) -> str:
    cleaned = str(value or "").strip().lower()
    cleaned = re.sub(r"[^a-z0-9&.\- ]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _company_tokens(value: str) -> list[str]:
    cleaned = normalize_company_name(value)
    for suffix in (" corporation", " corp", " company", " co", " incorporated", " inc", " llc", " ltd", " holdings", " holding", " group"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)].strip()
    cleaned = cleaned.replace("&", " and ")
    return [token for token in re.split(r"[^a-z0-9]+", cleaned) if token]


def _discovery_id(company: str, provider: str, target: str) -> str:
    raw = f"{normalize_company_name(company)}|{provider.strip().lower()}|{target.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _score_company_match(company: str, candidate_name: str, domain: str) -> float:
    company_tokens = set(_company_tokens(company))
    candidate_tokens = set(_company_tokens(candidate_name or domain))
    if not company_tokens:
        return 0.0
    overlap = len(company_tokens & candidate_tokens) / max(len(company_tokens), 1)
    compact = "".join(_company_tokens(company))
    compact_candidate = "".join(_company_tokens(candidate_name or ""))
    compact_domain = re.sub(r"[^a-z0-9]+", "", (domain or "").split(".")[0].lower())
    score = overlap
    if compact and compact == compact_candidate:
        score += 0.5
    if compact and compact in compact_domain:
        score += 0.35
    return score


def _extract_links(html: str, *, base_url: str) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for href in LINK_PATTERN.findall(html or ""):
        absolute = urljoin(base_url, href.strip())
        if not absolute.startswith("http"):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        links.append(absolute)
    return links


def _is_same_registered_domain(link: str, official_domain: str) -> bool:
    link_host = urlparse(link).hostname or ""
    official_host = (official_domain or "").lower()
    return bool(link_host and official_host and (link_host == official_host or link_host.endswith(f".{official_host}")))


def _career_link_priority(link: str) -> tuple[int, int]:
    lower = link.lower()
    hint_score = 0
    for idx, token in enumerate(CAREER_LINK_HINTS):
        if token in lower:
            hint_score = max(hint_score, len(CAREER_LINK_HINTS) - idx)
    return (hint_score, -len(lower))


def _extract_company_page_candidates(links: list[str], official_domain: str) -> list[str]:
    candidates: list[str] = []
    for link in links:
        if not _is_same_registered_domain(link, official_domain):
            continue
        lower = link.lower()
        if any(token in lower for token in CAREER_LINK_HINTS):
            candidates.append(link)
    candidates = sorted(set(candidates), key=_career_link_priority, reverse=True)
    return candidates[:6]


def _parse_greenhouse_target(link: str) -> str:
    path_parts = [part for part in urlparse(link).path.split("/") if part]
    return path_parts[0] if path_parts else ""


def _parse_lever_target(link: str) -> str:
    path_parts = [part for part in urlparse(link).path.split("/") if part]
    return path_parts[0] if path_parts else ""


def _parse_workday_target(link: str) -> str:
    parsed = urlparse(link)
    base = f"{parsed.scheme}://{parsed.netloc}"
    path_parts = [part for part in parsed.path.split("/") if part]
    if "wday" in path_parts and "cxs" in path_parts:
        return f"{base}{parsed.path.rstrip('/')}"
    tenant = (parsed.hostname or "").split(".")[0]
    site_name = ""
    for part in path_parts:
        if part.lower() in {"job", "jobs", "recruiting"}:
            continue
        if LOCALE_SEGMENT_PATTERN.match(part):
            continue
        site_name = part
        break
    if not site_name:
        site_name = tenant
    return f"{base}/wday/cxs/{tenant}/{site_name}/jobs"


def _parse_icims_target(link: str) -> str:
    parsed = urlparse(link)
    cleaned = link.strip()
    lower = cleaned.lower()
    if "social.icims.com/job/" in lower:
        return cleaned
    if "/jobs/" in lower and "/job" in lower:
        separator = "&" if parsed.query else "?"
        if "in_iframe=1" not in lower:
            cleaned = f"{cleaned}{separator}in_iframe=1"
        if "mode=" not in lower:
            separator = "&" if urlparse(cleaned).query else "?"
            cleaned = f"{cleaned}{separator}mode=view"
        return cleaned
    if "/careers-home/jobs" in lower or "/jobs/search" in lower:
        separator = "&" if parsed.query else "?"
        if "in_iframe=1" not in lower:
            return f"{cleaned}{separator}in_iframe=1"
        return cleaned
    return cleaned


def _parse_ats_link(link: str) -> dict[str, str] | None:
    parsed = urlparse(link)
    host = (parsed.hostname or "").lower()
    for provider, patterns in ATS_HOST_PATTERNS.items():
        if not any(pattern in host or pattern in link.lower() for pattern in patterns):
            continue
        if provider == "greenhouse":
            target = _parse_greenhouse_target(link)
        elif provider == "lever":
            target = _parse_lever_target(link)
        elif provider == "workday":
            target = _parse_workday_target(link)
        elif provider == "icims":
            target = _parse_icims_target(link)
        else:
            target = link
        if not target:
            return None
        return {"ats_provider": provider, "ats_target": target, "source_url": link}
    return None


def _seed_records_for_company(company: str) -> list[dict[str, Any]]:
    normalized = normalize_company_name(company)
    records = []
    for seed in STATIC_DISCOVERY_SEEDS.get(normalized, []):
        records.append(
            {
                "company": company,
                "official_domain": urlparse(seed.get("careers_url", "")).hostname or "",
                "careers_url": seed.get("careers_url", ""),
                "ats_provider": seed.get("ats_provider", ""),
                "ats_target": seed.get("ats_target", ""),
                "source_url": seed.get("careers_url", ""),
                "status": "active",
                "confidence": 0.95,
            }
        )
    return records


def _load_cached_company_records(company: str, *, db_path=None) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT company, official_domain, careers_url, ats_provider, ats_target, source_url, status, confidence, updated_at
            FROM career_site_discovery
            WHERE normalized_company = ?
            ORDER BY confidence DESC, updated_at DESC
            """,
            (normalize_company_name(company),),
        ).fetchall()
    now = datetime.now(timezone.utc)
    active_cutoff = now - timedelta(days=max(1, int(settings.career_discovery_cache_days or 14)))
    unresolved_cutoff = now - timedelta(days=3)
    filtered: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            updated_at = datetime.fromisoformat(str(item.get("updated_at") or ""))
        except ValueError:
            continue
        status = str(item.get("status") or "").strip().lower()
        cutoff = unresolved_cutoff if status != "active" else active_cutoff
        if updated_at >= cutoff:
            filtered.append(item)
    return filtered


def _save_company_records(company: str, rows: list[dict[str, Any]], *, db_path=None) -> None:
    normalized = normalize_company_name(company)
    timestamp = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            "DELETE FROM career_site_discovery WHERE normalized_company = ?",
            (normalized,),
        )
        for row in rows:
            provider = str(row.get("ats_provider", "") or "").strip().lower()
            target = str(row.get("ats_target", "") or "").strip()
            status = str(row.get("status", "active") or "active").strip().lower()
            conn.execute(
                """
                INSERT INTO career_site_discovery (
                    id, normalized_company, company, official_domain, careers_url, ats_provider,
                    ats_target, source_url, status, confidence, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _discovery_id(company, provider or status, target or status),
                    normalized,
                    str(row.get("company") or company).strip() or company,
                    str(row.get("official_domain") or "").strip().lower(),
                    str(row.get("careers_url") or "").strip(),
                    provider,
                    target,
                    str(row.get("source_url") or "").strip(),
                    status,
                    float(row.get("confidence", 0.6) or 0.6),
                    timestamp,
                    timestamp,
                ),
            )
        conn.commit()


async def _resolve_official_domain(company: str, client: httpx.AsyncClient) -> str:
    response = await _request_with_retries(
        client,
        "GET",
        "https://autocomplete.clearbit.com/v1/companies/suggest",
        params={"query": company},
        headers=REQUEST_HEADERS,
    )
    response.raise_for_status()
    candidates = response.json()
    best_domain = ""
    best_score = 0.0
    for item in candidates[:8]:
        domain = str(item.get("domain") or "").strip().lower()
        if not domain:
            continue
        candidate_name = str(item.get("name") or "").strip()
        score = _score_company_match(company, candidate_name, domain)
        if score > best_score:
            best_score = score
            best_domain = domain
    return best_domain if best_score >= 0.6 else ""


async def _fetch_text(url: str, client: httpx.AsyncClient) -> tuple[str, str]:
    response = await _request_with_retries(client, "GET", url, headers=REQUEST_HEADERS, follow_redirects=True)
    if response.status_code >= 400:
        return str(response.url), ""
    content_type = response.headers.get("content-type", "").lower()
    if "html" not in content_type and "text" not in content_type:
        return str(response.url), ""
    return str(response.url), response.text


async def _discover_company_records(company: str, client: httpx.AsyncClient) -> list[dict[str, Any]]:
    seed_rows = _seed_records_for_company(company)
    if seed_rows:
        return seed_rows

    official_domain = await _resolve_official_domain(company, client)
    if not official_domain:
        return [{"company": company, "status": "unresolved", "confidence": 0.1}]

    homepage_url = f"https://{official_domain}"
    homepage_final_url, homepage_html = await _fetch_text(homepage_url, client)
    pages_to_scan = [homepage_final_url]
    page_html: dict[str, str] = {homepage_final_url: homepage_html}

    common_paths = [
        "/careers",
        "/jobs",
        "/careers/",
        "/jobs/",
        "/careers/jobs",
        "/company/careers",
        "/about/careers",
        "/join-us",
        "/join",
        "/work-with-us",
        "/us/en/careers",
        "/en-us/careers",
        "/global/en/careers",
        "/global/en/search-results",
        "/search-results",
    ]
    for path in common_paths:
        pages_to_scan.append(urljoin(homepage_final_url, path))

    if homepage_html:
        pages_to_scan.extend(_extract_company_page_candidates(_extract_links(homepage_html, base_url=homepage_final_url), official_domain))

    unique_pages: list[str] = []
    seen_pages: set[str] = set()
    for page in pages_to_scan:
        if page in seen_pages:
            continue
        seen_pages.add(page)
        unique_pages.append(page)
        if len(unique_pages) >= 8:
            break

    discovered: dict[tuple[str, str], dict[str, Any]] = {}
    for page in unique_pages:
        html = page_html.get(page)
        if html is None:
            _, html = await _fetch_text(page, client)
        if not html:
            continue
        links = _extract_links(html, base_url=page)
        for link in links:
            parsed = _parse_ats_link(link)
            if not parsed:
                continue
            key = (parsed["ats_provider"], parsed["ats_target"])
            existing = discovered.get(key)
            row = {
                "company": company,
                "official_domain": official_domain,
                "careers_url": page,
                "ats_provider": parsed["ats_provider"],
                "ats_target": parsed["ats_target"],
                "source_url": parsed["source_url"],
                "status": "active" if parsed["ats_provider"] in SUPPORTED_ATS_PROVIDERS else "unsupported",
                "confidence": 0.9 if parsed["ats_provider"] in SUPPORTED_ATS_PROVIDERS else 0.5,
            }
            if existing is None or row["confidence"] > existing["confidence"]:
                discovered[key] = row

    if not discovered:
        return [
            {
                "company": company,
                "official_domain": official_domain,
                "careers_url": homepage_final_url,
                "status": "unresolved",
                "confidence": 0.2,
            }
        ]
    return list(discovered.values())


async def discover_company_targets(
    companies: list[str],
    *,
    source: str,
    db_path=None,
) -> list[dict[str, str]]:
    normalized_source = str(source or "").strip().lower()
    ordered_targets: list[dict[str, str]] = []
    seen_targets: set[str] = set()

    deduped_companies: list[str] = []
    seen_companies: set[str] = set()
    for company in companies:
        normalized_company = normalize_company_name(company)
        if not normalized_company or normalized_company in seen_companies:
            continue
        seen_companies.add(normalized_company)
        deduped_companies.append(str(company).strip())

    cached_companies: set[str] = set()
    for company in deduped_companies:
        if normalize_company_name(company) in STATIC_DISCOVERY_SEEDS:
            seed_rows = _seed_records_for_company(company)
            _save_company_records(company, seed_rows, db_path=db_path)
            cached_companies.add(normalize_company_name(company))
            for row in seed_rows:
                if row.get("status") != "active" or row.get("ats_provider") != normalized_source:
                    continue
                dedupe_key = f"{row.get('ats_provider')}|{row.get('ats_target')}"
                if dedupe_key in seen_targets:
                    continue
                seen_targets.add(dedupe_key)
                ordered_targets.append(
                    {
                        "company": str(row.get("company") or company).strip(),
                        "target": str(row.get("ats_target") or "").strip(),
                        "careers_url": str(row.get("careers_url") or "").strip(),
                        "official_domain": str(row.get("official_domain") or "").strip(),
                    }
                )
            continue
        cached_rows = _load_cached_company_records(company, db_path=db_path)
        if cached_rows:
            cached_companies.add(normalize_company_name(company))
            for row in cached_rows:
                if row.get("status") != "active" or row.get("ats_provider") != normalized_source:
                    continue
                dedupe_key = f"{row.get('ats_provider')}|{row.get('ats_target')}"
                if dedupe_key in seen_targets:
                    continue
                seen_targets.add(dedupe_key)
                ordered_targets.append(
                    {
                        "company": str(row.get("company") or company).strip(),
                        "target": str(row.get("ats_target") or "").strip(),
                        "careers_url": str(row.get("careers_url") or "").strip(),
                        "official_domain": str(row.get("official_domain") or "").strip(),
                    }
                )

    pending = [company for company in deduped_companies if normalize_company_name(company) not in cached_companies]
    if pending:
        limits = httpx.Limits(max_keepalive_connections=10, max_connections=20)
        async with httpx.AsyncClient(timeout=20.0, limits=limits) as client:
            semaphore = asyncio.Semaphore(8)

            async def _discover_one(company: str) -> tuple[str, list[dict[str, Any]]]:
                async with semaphore:
                    try:
                        rows = await _discover_company_records(company, client)
                    except Exception:
                        rows = [{"company": company, "status": "unresolved", "confidence": 0.05}]
                    return company, rows

            results = await asyncio.gather(*[_discover_one(company) for company in pending])
            for company, rows in results:
                try:
                    _save_company_records(company, rows, db_path=db_path)
                    for row in rows:
                        if row.get("status") != "active" or row.get("ats_provider") != normalized_source:
                            continue
                        dedupe_key = f"{row.get('ats_provider')}|{row.get('ats_target')}"
                        if dedupe_key in seen_targets:
                            continue
                        seen_targets.add(dedupe_key)
                        ordered_targets.append(
                            {
                                "company": str(row.get("company") or company).strip(),
                                "target": str(row.get("ats_target") or "").strip(),
                                "careers_url": str(row.get("careers_url") or "").strip(),
                                "official_domain": str(row.get("official_domain") or "").strip(),
                            }
                        )
                except Exception:
                    continue

    return ordered_targets
