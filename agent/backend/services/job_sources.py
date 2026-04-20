from __future__ import annotations

import asyncio
import codecs
import html
import json
import random
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import httpx

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
]

REQUEST_HEADERS = {
    "User-Agent": _USER_AGENTS[0],
}


def _random_headers() -> dict[str, str]:
    """Return request headers with a randomly chosen User-Agent."""
    return {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }
LINK_PATTERN = re.compile(r"""href\s*=\s*["']([^"'#]+)["']""", re.I)
TAG_PATTERN = re.compile(r"<[^>]+>")
WHITESPACE_PATTERN = re.compile(r"\s+")


async def _request_with_retries(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = await client.request(method, url, **kwargs)
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                await asyncio.sleep(0.8 * (attempt + 1))
                continue
            return response
        except (httpx.TimeoutException, httpx.TransportError, httpx.DecodingError) as exc:
            last_error = exc
            if attempt >= 2:
                raise
            await asyncio.sleep(0.8 * (attempt + 1))
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Request failed without response for {url}")


def _strip_html(value: str) -> str:
    text = TAG_PATTERN.sub(" ", str(value or ""))
    text = html.unescape(text)
    return WHITESPACE_PATTERN.sub(" ", text).strip()


def _extract_links(page_html: str, *, base_url: str) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for href in LINK_PATTERN.findall(page_html or ""):
        absolute = urljoin(base_url, html.unescape(href.strip()))
        if not absolute.startswith("http") or absolute in seen:
            continue
        seen.add(absolute)
        links.append(absolute)
    return links


def _extract_json_array(source_text: str, marker: str) -> list[dict[str, Any]]:
    start = source_text.find(marker)
    if start < 0:
        return []
    start = start + len(marker) - 1
    depth = 0
    end = None
    for index in range(start, len(source_text)):
        char = source_text[index]
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                end = index + 1
                break
    if end is None:
        return []
    try:
        return json.loads(source_text[start:end])
    except json.JSONDecodeError:
        return []


def _match_first(patterns: list[str], text: str) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I | re.S)
        if match:
            return match.group(1)
    return ""


LINKEDIN_SEARCH_CARD_TITLE = re.compile(
    r'<h3[^>]*class="[^"]*base-search-card__title[^"]*"[^>]*>(.*?)</h3>', re.I | re.S
)
LINKEDIN_SEARCH_CARD_SUBTITLE = re.compile(
    r'<h4[^>]*class="[^"]*base-search-card__subtitle[^"]*"[^>]*>(.*?)</h4>', re.I | re.S
)
LINKEDIN_SEARCH_CARD_LOCATION = re.compile(
    r'<span[^>]*class="[^"]*job-search-card__location[^"]*"[^>]*>(.*?)</span>', re.I | re.S
)
LINKEDIN_SEARCH_CARD_LINK = re.compile(
    r'<a[^>]*class="[^"]*base-card__full-link[^"]*"[^>]*href="([^"]+)"', re.I | re.S
)
LINKEDIN_JD_PATTERNS = [
    re.compile(r'<div[^>]*class="[^"]*show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>', re.I | re.S),
    re.compile(r'<div[^>]*class="[^"]*description__text[^"]*"[^>]*>(.*?)</div>', re.I | re.S),
]


async def _fetch_linkedin_detail(client: httpx.AsyncClient, url: str) -> str:
    """Fetch a single LinkedIn job detail page and extract the JD text."""
    try:
        response = await _request_with_retries(client, "GET", url, headers=_random_headers(), follow_redirects=True)
        if response.status_code in {403, 429}:
            return ""
        if response.status_code >= 400:
            return ""
        page_html = response.text
        for pattern in LINKEDIN_JD_PATTERNS:
            match = pattern.search(page_html)
            if match:
                return _strip_html(match.group(1))
        return ""
    except Exception:
        return ""


def _parse_linkedin_job_cards(page_html: str) -> list[dict[str, str]]:
    """Parse LinkedIn guest search HTML into a list of raw card dicts."""
    cards: list[dict[str, str]] = []
    # Split on base-card or list-item boundaries
    card_chunks = re.split(r'<(?:div|li)[^>]*class="[^"]*base-card[^"]*"', page_html)
    for chunk in card_chunks[1:]:  # skip text before first card
        title_match = LINKEDIN_SEARCH_CARD_TITLE.search(chunk)
        company_match = LINKEDIN_SEARCH_CARD_SUBTITLE.search(chunk)
        location_match = LINKEDIN_SEARCH_CARD_LOCATION.search(chunk)
        link_match = LINKEDIN_SEARCH_CARD_LINK.search(chunk)
        if not title_match:
            continue
        url = ""
        if link_match:
            url = html.unescape(link_match.group(1).strip())
            # Strip tracking query params
            url = url.split("?")[0]
        cards.append({
            "title": _strip_html(title_match.group(1)),
            "company": _strip_html(company_match.group(1)) if company_match else "",
            "location": _strip_html(location_match.group(1)) if location_match else "",
            "url": url,
        })
    return cards


async def fetch_linkedin_jobs(
    *,
    keywords: list[str] | None = None,
    location: str = "",
    company_name: str = "",
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Fetch jobs from LinkedIn's public guest job search API.

    Uses the unauthenticated ``/jobs-guest/jobs/api/seeMoreJobPostings/search``
    endpoint, parses the returned HTML cards, and optionally fetches each
    detail page for the full job description text.

    Rate-limits itself (1-2 s between requests) and gracefully handles
    429/403 responses by returning whatever has been collected so far.
    """
    query_parts: list[str] = []
    if company_name:
        query_parts.append(company_name)
    if keywords:
        query_parts.extend(keywords)
    if not query_parts:
        return []

    query_string = " ".join(query_parts)
    params: dict[str, str] = {"keywords": query_string, "start": "0"}
    if location:
        params["location"] = location

    search_url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?" + urlencode(params)

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        # Initial delay to mimic a human opening the page
        await asyncio.sleep(random.uniform(2.0, 4.0))

        try:
            response = await _request_with_retries(client, "GET", search_url, headers=_random_headers())
        except Exception:
            return []

        if response.status_code in {403, 429}:
            return []
        if response.status_code >= 400:
            return []

        cards = _parse_linkedin_job_cards(response.text)[:limit]
        if not cards:
            return []

        jobs: list[dict[str, Any]] = []
        for card in cards:
            jobs.append({
                "title": card["title"],
                "company": card["company"] or company_name,
                "location": card["location"],
                "url": card["url"],
                "source": "linkedin",
                "jd_text": "",
                "source_urls": [card["url"]] if card["url"] else [search_url],
            })

        # Fetch detail pages sequentially with human-like delays to avoid detection.
        # Delays increase slightly over time to mimic reading behaviour.
        for index, job in enumerate(jobs):
            if not job["url"]:
                continue
            # Base delay 3-6s, grows ~0.5s per page (human reads each listing)
            base_delay = random.uniform(3.0, 6.0) + index * random.uniform(0.3, 0.7)
            # Occasional longer pause every ~5 pages (human scrolling / thinking)
            if index > 0 and index % 5 == 0:
                base_delay += random.uniform(4.0, 8.0)
            await asyncio.sleep(base_delay)

            jd_text = await _fetch_linkedin_detail(client, job["url"])
            if jd_text:
                jobs[index]["jd_text"] = jd_text

            # Check if we're being blocked — stop gracefully
            if response.status_code in {403, 429}:
                break

    return jobs


async def fetch_greenhouse_jobs(company: str, limit: int = 20) -> list[dict[str, Any]]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await _request_with_retries(client, "GET", url, headers=REQUEST_HEADERS)
        if response.status_code == 404:
            return []
        response.raise_for_status()
        data = response.json()

    jobs = []
    for item in data.get("jobs", [])[:limit]:
        jobs.append(
            {
                "title": item.get("title", ""),
                "company": company,
                "location": (item.get("location") or {}).get("name", ""),
                "url": item.get("absolute_url", ""),
                "source": "greenhouse",
                "jd_text": item.get("content", "") or item.get("updated_at", ""),
                "source_urls": [item.get("absolute_url", "")],
            }
        )
    return jobs


async def fetch_lever_jobs(company: str, limit: int = 20) -> list[dict[str, Any]]:
    url = f"https://api.lever.co/v0/postings/{company}?mode=json"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await _request_with_retries(client, "GET", url, headers=REQUEST_HEADERS)
        if response.status_code == 404:
            return []
        response.raise_for_status()
        data = response.json()

    jobs = []
    for item in data[:limit]:
        categories = item.get("categories") or {}
        location = categories.get("location", "")
        description = "\n".join(
            [
                item.get("descriptionPlain", "") or "",
                item.get("listsPlain", "") or "",
                item.get("additionalPlain", "") or "",
            ]
        ).strip()
        jobs.append(
            {
                "title": item.get("text", ""),
                "company": company,
                "location": location,
                "url": item.get("hostedUrl", ""),
                "source": "lever",
                "jd_text": description,
                "source_urls": [item.get("hostedUrl", "")],
            }
        )
    return jobs


async def fetch_ashby_jobs(target: str, limit: int = 20) -> list[dict[str, Any]]:
    board_url = str(target or "").strip()
    if not board_url:
        return []
    if not board_url.startswith("http"):
        board_url = f"https://jobs.ashbyhq.com/{board_url.strip('/')}"
    company_slug = urlparse(board_url).path.strip("/").split("/")[0]
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await _request_with_retries(client, "GET", board_url, headers=REQUEST_HEADERS)
        if response.status_code not in range(200, 300):
            return []
        page_html = response.text

    postings = _extract_json_array(page_html, '"jobPostings":[')
    jobs = []
    for item in postings[:limit]:
        secondary_locations = [
            str(location.get("locationName") or "").strip()
            for location in (item.get("secondaryLocations") or [])
            if str(location.get("locationName") or "").strip()
        ]
        location_parts = [str(item.get("locationName") or "").strip()] + secondary_locations
        location = " | ".join(part for part in location_parts if part)
        description = "\n".join(
            [
                str(item.get("departmentName") or "").strip(),
                str(item.get("teamName") or "").strip(),
                str(item.get("workplaceType") or "").strip(),
                str(item.get("employmentType") or "").strip(),
                str(item.get("compensationTierSummary") or "").strip(),
            ]
        ).strip()
        jobs.append(
            {
                "title": str(item.get("title") or "").strip(),
                "company": company_slug,
                "location": location,
                "url": board_url,
                "source": "ashby",
                "jd_text": description,
                "source_urls": [board_url],
                "meta": {
                    "published_on": str(item.get("publishedDate") or "").strip(),
                    "job_posting_id": str(item.get("id") or "").strip(),
                    "job_id": str(item.get("jobId") or "").strip(),
                    "department": str(item.get("departmentName") or "").strip(),
                    "team": str(item.get("teamName") or "").strip(),
                },
            }
        )
    return jobs


async def _fetch_smartrecruiters_detail(client: httpx.AsyncClient, url: str) -> str:
    response = await _request_with_retries(client, "GET", url, headers=REQUEST_HEADERS, follow_redirects=True)
    if response.status_code >= 400:
        return ""
    page_html = response.text
    sections = []
    for pattern in [
        r'<section[^>]*id="st-jobDescription"[^>]*>(.*?)</section>',
        r'<section[^>]*id="st-qualifications"[^>]*>(.*?)</section>',
        r'<section[^>]*id="st-additionalInformation"[^>]*>(.*?)</section>',
    ]:
        match = re.search(pattern, page_html, flags=re.I | re.S)
        if match:
            sections.append(_strip_html(match.group(1)))
    if sections:
        return "\n".join(section for section in sections if section).strip()
    return _strip_html(_match_first([r'<meta\s+name="description"\s+content="(.*?)"'], page_html))


async def fetch_smartrecruiters_jobs(target: str, limit: int = 20) -> list[dict[str, Any]]:
    board_url = str(target or "").strip()
    if not board_url:
        return []
    if not board_url.startswith("http"):
        board_url = f"https://careers.smartrecruiters.com/{board_url.strip('/')}"

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await _request_with_retries(client, "GET", board_url, headers=REQUEST_HEADERS)
        if response.status_code not in range(200, 300):
            return []
        page_html = response.text
        final_board_url = str(response.url)

        section_pattern = re.compile(
            r'<section[^>]*class="openings-section[^"]*"[^>]*>.*?<h3[^>]*class="opening-title[^"]*"[^>]*>(.*?)</h3>.*?<ul[^>]*class="opening-jobs[^"]*"[^>]*>(.*?)</ul>',
            re.I | re.S,
        )
        job_link_pattern = re.compile(
            r'<a[^>]*href="(https://jobs\.smartrecruiters\.com/[^"]+)"[^>]*>.*?<h4[^>]*class="details-title job-title[^"]*"[^>]*>(.*?)</h4>',
            re.I | re.S,
        )

        jobs: list[dict[str, Any]] = []
        detail_tasks: list[tuple[str, str, str]] = []
        for location_html, group_html in section_pattern.findall(page_html):
            location = _strip_html(location_html)
            for detail_url, title_html in job_link_pattern.findall(group_html):
                title = _strip_html(title_html)
                if not title:
                    continue
                jobs.append(
                    {
                        "title": title,
                        "company": urlparse(final_board_url).path.strip("/").split("/")[-1] or target,
                        "location": location,
                        "url": detail_url,
                        "source": "smartrecruiters",
                        "jd_text": "",
                        "source_urls": [detail_url, final_board_url],
                    }
                )
                detail_tasks.append((detail_url, title, location))
                if len(jobs) >= limit:
                    break
            if len(jobs) >= limit:
                break

        detail_results = await asyncio.gather(*[_fetch_smartrecruiters_detail(client, detail_url) for detail_url, _, _ in detail_tasks], return_exceptions=True)
        for index, detail_text in enumerate(detail_results):
            if isinstance(detail_text, Exception):
                continue
            jobs[index]["jd_text"] = detail_text
        return jobs


def _jobvite_board_url(target: str) -> str:
    cleaned = str(target or "").strip()
    if cleaned.startswith("http"):
        return cleaned
    return f"https://jobs.jobvite.com/{cleaned.strip('/')}"


async def _fetch_jobvite_detail(client: httpx.AsyncClient, url: str) -> str:
    response = await _request_with_retries(client, "GET", url, headers=REQUEST_HEADERS, follow_redirects=True)
    if response.status_code >= 400:
        return ""
    page_html = response.text
    section = _match_first(
        [
            r'<div[^>]*class="jv-job-detail-description"[^>]*>(.*?)</div>',
            r'<section[^>]*class="jv-job-detail-description"[^>]*>(.*?)</section>',
        ],
        page_html,
    )
    return _strip_html(section or page_html)


async def fetch_jobvite_jobs(target: str, limit: int = 20) -> list[dict[str, Any]]:
    board_url = _jobvite_board_url(target)
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await _request_with_retries(client, "GET", board_url, headers=REQUEST_HEADERS)
        if response.status_code not in range(200, 300):
            return []
        page_html = response.text
        final_board_url = str(response.url)

        row_pattern = re.compile(
            r'<a href="(/[^"]+/job/[^"]+)">(.*?)</a>.*?<td[^>]*class="jv-job-list-location"[^>]*>(.*?)</td>',
            re.I | re.S,
        )
        jobs: list[dict[str, Any]] = []
        detail_urls: list[str] = []
        company_slug = urlparse(final_board_url).path.strip("/").split("/")[0]
        for relative_url, title_html, location_html in row_pattern.findall(page_html):
            detail_url = urljoin(final_board_url, relative_url)
            jobs.append(
                {
                    "title": _strip_html(title_html),
                    "company": company_slug,
                    "location": _strip_html(location_html),
                    "url": detail_url,
                    "source": "jobvite",
                    "jd_text": "",
                    "source_urls": [detail_url, final_board_url],
                }
            )
            detail_urls.append(detail_url)
            if len(jobs) >= limit:
                break

        detail_results = await asyncio.gather(*[_fetch_jobvite_detail(client, detail_url) for detail_url in detail_urls], return_exceptions=True)
        for index, detail_text in enumerate(detail_results):
            if isinstance(detail_text, Exception):
                continue
            jobs[index]["jd_text"] = detail_text
        return jobs


async def _fetch_icims_detail(client: httpx.AsyncClient, url: str) -> str:
    response = await _request_with_retries(client, "GET", url, headers=REQUEST_HEADERS, follow_redirects=True)
    if response.status_code >= 400:
        return ""
    return response.text


def _with_query_params(url: str, **params: str) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in params.items():
        if value is not None:
            query[key] = value
    return urlunparse(parsed._replace(query=urlencode(query)))


def _normalize_icims_target(url: str) -> str:
    cleaned = str(url or "").strip()
    if not cleaned:
        return ""
    # Add protocol if missing (bare hostnames like "careers-ozk.icims.com")
    if not cleaned.startswith(("http://", "https://")):
        cleaned = f"https://{cleaned}"
    lower = cleaned.lower()
    if "social.icims.com/job/" in lower:
        return cleaned
    if "/jobs/" in lower and "/job" in lower:
        cleaned = _with_query_params(cleaned, in_iframe="1", mode="view")
        return cleaned
    if "/careers-home/jobs" in lower or "/jobs/search" in lower:
        return _with_query_params(cleaned, in_iframe="1")
    return cleaned


def _decode_js_escaped_fragment(value: str) -> str:
    fragment = str(value or "")
    if not fragment:
        return ""
    fragment = fragment.replace("\\/", "/")
    try:
        fragment = codecs.decode(fragment, "unicode_escape")
    except Exception:
        pass
    return html.unescape(fragment)


def _extract_icims_location(page_html: str, title_text: str) -> str:
    location = _match_first(
        [
            r'<h2[^>]*class="icims-page-subtitle"[^>]*>\s*([^<]{2,120})\s*</h2>',
            r'Location</dt>\s*<dd[^>]*>(.*?)</dd>',
            r'"addressLocality":"(.*?)"',
        ],
        page_html,
    )
    if location:
        return _strip_html(_decode_js_escaped_fragment(location))
    title_match = re.search(r"\s+in\s+(.+?)\s+\|\s+Careers at\s+", title_text, flags=re.I)
    if title_match:
        return _strip_html(title_match.group(1))
    return ""


def _parse_icims_detail(page_html: str, detail_url: str) -> dict[str, str]:
    title_text = _match_first(
        [
            r'<h1[^>]*>(.*?)</h1>',
            r'<meta[^>]+property="og:title"[^>]+content="(.*?)"',
            r'<title>(.*?)</title>',
        ],
        page_html,
    )
    title = _strip_html(_decode_js_escaped_fragment(title_text))
    title = re.sub(r"\s+\|\s+iCIMS Social Distribution$", "", title, flags=re.I).strip()
    title = re.sub(r"\s+\|\s+Careers at\s+.+$", "", title, flags=re.I).strip()
    if not title:
        title = detail_url.rstrip("/").rsplit("/", 1)[-1]

    sections: list[str] = []
    for pattern in [
        r'Overview<\\/h2>\s*(.*?)(?:Responsibilities<\\/h2>|Qualifications<\\/h2>|Options<\\/h2>|Need help)',
        r'Responsibilities<\\/h2>\s*(.*?)(?:Qualifications<\\/h2>|Options<\\/h2>|Need help)',
        r'Qualifications<\\/h2>\s*(.*?)(?:Options<\\/h2>|Need help)',
        r'<meta[^>]+property="og:description"[^>]+content="(.*?)"',
        r'<div[^>]*class="iCIMS_JobContent"[^>]*>(.*?)</div>',
        r'<div[^>]*class="job-description"[^>]*>(.*?)</div>',
    ]:
        match = re.search(pattern, page_html, flags=re.I | re.S)
        if match:
            section = _strip_html(_decode_js_escaped_fragment(match.group(1)))
            if section and section not in sections:
                sections.append(section)
    jd_text = "\n".join(sections).strip()
    return {
        "title": title,
        "location": _extract_icims_location(page_html, title_text),
        "jd_text": jd_text,
    }


async def fetch_icims_jobs(target: str, limit: int = 20) -> list[dict[str, Any]]:
    board_url = _normalize_icims_target(str(target or "").strip())
    if not board_url:
        return []
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await _request_with_retries(client, "GET", board_url, headers=REQUEST_HEADERS)
        if response.status_code not in range(200, 300):
            return []
        page_html = response.text
        final_board_url = str(response.url)

        final_lower = final_board_url.lower()
        if "social.icims.com/job/" in final_lower or re.search(r"/jobs/\d+/.*?/job(?:[/?]|$)", final_lower):
            detail = _parse_icims_detail(page_html, final_board_url)
            return [
                {
                    "title": detail["title"],
                    "company": urlparse(final_board_url).hostname or final_board_url,
                    "location": detail["location"],
                    "url": final_board_url,
                    "source": "icims",
                    "jd_text": detail["jd_text"],
                    "source_urls": [final_board_url],
                }
            ]

        detail_links = []
        for link in _extract_links(page_html, base_url=final_board_url):
            lower = link.lower()
            if "social.icims.com/job/" in lower:
                detail_links.append(link)
                continue
            if re.search(r"icims\.com/jobs/\d+/.*?/job(?:[/?]|$)", lower):
                detail_links.append(_normalize_icims_target(link))
        detail_links = list(dict.fromkeys(detail_links))[:limit]

        jobs = []
        detail_results = await asyncio.gather(*[_fetch_icims_detail(client, link) for link in detail_links], return_exceptions=True)
        for detail_url, detail_html in zip(detail_links, detail_results):
            if isinstance(detail_html, Exception):
                continue
            detail = _parse_icims_detail(detail_html, detail_url)
            jobs.append(
                {
                    "title": detail["title"],
                    "company": urlparse(final_board_url).hostname or final_board_url,
                    "location": detail["location"],
                    "url": detail_url,
                    "source": "icims",
                    "jd_text": detail["jd_text"],
                    "source_urls": [detail_url, final_board_url],
                }
            )
        return jobs


async def _fetch_taleo_detail(client: httpx.AsyncClient, url: str, fallback_title: str = "", fallback_location: str = "") -> dict[str, str]:
    response = await _request_with_retries(client, "GET", url, headers=REQUEST_HEADERS, follow_redirects=True)
    if response.status_code >= 400:
        return {"title": fallback_title, "location": fallback_location, "jd_text": ""}
    page_html = response.text
    plain = _strip_html(page_html)
    description = _match_first(
        [
            r'Job Summary(.*?)(?:Go to the footer|Apply|Refer This Job)',
            r'Description(.*?)(?:Qualifications|Job Requirements|Apply)',
        ],
        plain,
    )
    return {
        "title": fallback_title or _match_first([r'<title>(.*?)</title>'], page_html) or "Taleo role",
        "location": fallback_location,
        "jd_text": _strip_html(description or plain),
    }


async def fetch_taleo_jobs(target: str, limit: int = 20) -> list[dict[str, Any]]:
    board_url = str(target or "").strip()
    if not board_url:
        return []
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await _request_with_retries(client, "GET", board_url, headers=REQUEST_HEADERS)
        if response.status_code not in range(200, 300):
            return []
        page_html = response.text
        final_url = str(response.url)

        detail_pattern = re.compile(
            r'<a[^>]*href="([^"]*(?:jobdetail|jobview)\.ftl[^"]*)"[^>]*>(.*?)</a>',
            re.I | re.S,
        )
        jobs: list[dict[str, Any]] = []
        detail_refs: list[tuple[str, str]] = []
        for href, title_html in detail_pattern.findall(page_html):
            detail_url = urljoin(final_url, href)
            title = _strip_html(title_html)
            if not title:
                continue
            jobs.append(
                {
                    "title": title,
                    "company": urlparse(final_url).hostname or final_url,
                    "location": "",
                    "url": detail_url,
                    "source": "taleo",
                    "jd_text": "",
                    "source_urls": [detail_url, final_url],
                }
            )
            detail_refs.append((detail_url, title))
            if len(jobs) >= limit:
                break

        if not jobs and ("jobdetail.ftl" in final_url.lower() or "jobview.ftl" in final_url.lower()):
            detail = await _fetch_taleo_detail(client, final_url)
            if detail["jd_text"]:
                return [
                    {
                        "title": detail["title"],
                        "company": urlparse(final_url).hostname or final_url,
                        "location": detail["location"],
                        "url": final_url,
                        "source": "taleo",
                        "jd_text": detail["jd_text"],
                        "source_urls": [final_url],
                    }
                ]
            return []

        detail_results = await asyncio.gather(
            *[_fetch_taleo_detail(client, detail_url, fallback_title=title) for detail_url, title in detail_refs],
            return_exceptions=True,
        )
        for index, detail in enumerate(detail_results):
            if isinstance(detail, Exception):
                continue
            jobs[index]["title"] = detail.get("title") or jobs[index]["title"]
            jobs[index]["location"] = detail.get("location") or jobs[index]["location"]
            jobs[index]["jd_text"] = detail.get("jd_text") or jobs[index]["jd_text"]
        return jobs


# ---------------------------------------------------------------------------
# Indeed
# ---------------------------------------------------------------------------

INDEED_CARD_TITLE = re.compile(
    r'<h2[^>]*class="[^"]*jobTitle[^"]*"[^>]*>(.*?)</h2>', re.I | re.S,
)
INDEED_CARD_TITLE_ALT = re.compile(
    r'<a[^>]*class="[^"]*jcs-JobTitle[^"]*"[^>]*>(.*?)</a>', re.I | re.S,
)
INDEED_CARD_COMPANY = re.compile(
    r'<span[^>]*class="[^"]*companyName[^"]*"[^>]*>(.*?)</span>', re.I | re.S,
)
INDEED_CARD_COMPANY_ALT = re.compile(
    r'data-company-name="([^"]+)"', re.I,
)
INDEED_CARD_LOCATION = re.compile(
    r'<div[^>]*class="[^"]*companyLocation[^"]*"[^>]*>(.*?)</div>', re.I | re.S,
)
INDEED_CARD_LINK = re.compile(
    r'<a[^>]*(?:class="[^"]*jcs-JobTitle[^"]*"|id="job_[^"]*")[^>]*href="([^"]+)"', re.I | re.S,
)
INDEED_JD_PATTERNS = [
    re.compile(r'<div[^>]*id="jobDescriptionText"[^>]*>(.*?)</div>', re.I | re.S),
    re.compile(r'<div[^>]*class="[^"]*jobsearch-jobDescriptionText[^"]*"[^>]*>(.*?)</div>', re.I | re.S),
]


def _parse_indeed_job_cards(page_html: str) -> list[dict[str, str]]:
    """Parse Indeed search result HTML into a list of raw card dicts."""
    cards: list[dict[str, str]] = []
    # Split on known job card boundaries
    card_chunks = re.split(
        r'<div[^>]*class="[^"]*(?:job_seen_beacon|resultContent)[^"]*"'
        r'|<td[^>]*class="[^"]*resultContent[^"]*"'
        r'|<div[^>]*class="[^"]*result\b[^"]*"',
        page_html,
    )
    for chunk in card_chunks[1:]:  # skip text before first card
        title_match = INDEED_CARD_TITLE.search(chunk) or INDEED_CARD_TITLE_ALT.search(chunk)
        company_match = INDEED_CARD_COMPANY.search(chunk) or INDEED_CARD_COMPANY_ALT.search(chunk)
        location_match = INDEED_CARD_LOCATION.search(chunk)
        link_match = INDEED_CARD_LINK.search(chunk)
        if not title_match:
            continue
        url = ""
        if link_match:
            raw_href = html.unescape(link_match.group(1).strip())
            if raw_href.startswith("/"):
                url = f"https://www.indeed.com{raw_href}"
            else:
                url = raw_href
            url = url.split("&from=")[0]  # trim tracking params
        cards.append({
            "title": _strip_html(title_match.group(1)),
            "company": _strip_html(company_match.group(1)) if company_match else "",
            "location": _strip_html(location_match.group(1)) if location_match else "",
            "url": url,
        })
    return cards




async def fetch_indeed_jobs(
    *,
    keywords: list[str] | None = None,
    location: str = "",
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Fetch jobs from Indeed using Playwright to bypass anti-bot captchas.

    Launches a headless Chromium browser, navigates to the search page,
    parses HTML job cards, and fetches detail pages for JD text.
    Uses human-like delays between page loads.
    """
    if not keywords:
        return []

    from playwright.async_api import async_playwright

    query_string = " ".join(keywords)
    params: dict[str, str] = {"q": query_string}
    if location:
        params["l"] = location
    search_url = "https://www.indeed.com/jobs?" + urlencode(params)

    jobs: list[dict[str, Any]] = []
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=random.choice(_USER_AGENTS),
                viewport={"width": 1280, "height": 900},
            )
            page = await context.new_page()

            await page.goto(search_url, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_timeout(int(random.uniform(2000, 4000)))

            page_html = await page.content()
            cards = _parse_indeed_job_cards(page_html)[:limit]

            for card in cards:
                jobs.append({
                    "title": card["title"],
                    "company": card["company"],
                    "location": card["location"],
                    "url": card["url"],
                    "source": "indeed",
                    "jd_text": "",
                    "source_urls": [card["url"]] if card["url"] else [search_url],
                })

            # Fetch detail pages with human-like delays
            for index, job in enumerate(jobs):
                if not job["url"]:
                    continue
                delay = random.uniform(3.0, 6.0) + index * random.uniform(0.3, 0.7)
                if index > 0 and index % 5 == 0:
                    delay += random.uniform(4.0, 8.0)
                await asyncio.sleep(delay)

                try:
                    await page.goto(job["url"], wait_until="domcontentloaded", timeout=25_000)
                    await page.wait_for_timeout(int(random.uniform(1500, 3000)))
                    detail_html = await page.content()
                    jd_text = _extract_indeed_jd(detail_html)
                    if jd_text:
                        jobs[index]["jd_text"] = jd_text
                except Exception:
                    continue

            await browser.close()
    except Exception:
        pass

    return jobs


def _extract_indeed_jd(page_html: str) -> str:
    """Extract JD text from an Indeed detail page."""
    for pattern in INDEED_JD_PATTERNS:
        match = pattern.search(page_html)
        if match:
            return _strip_html(match.group(1))
    return ""


# ---------------------------------------------------------------------------
# Glassdoor
# ---------------------------------------------------------------------------

GLASSDOOR_CARD_TITLE = re.compile(
    r'<a[^>]*class="[^"]*JobCard_jobTitle[^"]*"[^>]*>(.*?)</a>', re.I | re.S,
)
GLASSDOOR_CARD_TITLE_ALT = re.compile(
    r'<a[^>]*data-test="job-title"[^>]*>(.*?)</a>', re.I | re.S,
)
GLASSDOOR_CARD_COMPANY = re.compile(
    r'<span[^>]*class="[^"]*EmployerProfile_compactEmployerName[^"]*"[^>]*>(.*?)</span>', re.I | re.S,
)
GLASSDOOR_CARD_COMPANY_ALT = re.compile(
    r'<div[^>]*class="[^"]*employerName[^"]*"[^>]*>(.*?)</div>', re.I | re.S,
)
GLASSDOOR_CARD_LOCATION = re.compile(
    r'<div[^>]*class="[^"]*JobCard_location[^"]*"[^>]*>(.*?)</div>', re.I | re.S,
)
GLASSDOOR_CARD_LOCATION_ALT = re.compile(
    r'<span[^>]*class="[^"]*job-search-key-[^"]*location[^"]*"[^>]*>(.*?)</span>', re.I | re.S,
)
GLASSDOOR_CARD_LINK = re.compile(
    r'<a[^>]*(?:class="[^"]*JobCard_jobTitle[^"]*"|data-test="job-title")[^>]*href="([^"]+)"', re.I | re.S,
)
GLASSDOOR_JD_PATTERNS = [
    re.compile(r'<div[^>]*class="[^"]*JobDetails_jobDescription[^"]*"[^>]*>(.*?)</div>', re.I | re.S),
    re.compile(r'<div[^>]*class="[^"]*jobDescriptionContent[^"]*"[^>]*>(.*?)</div>', re.I | re.S),
]


def _parse_glassdoor_job_cards(page_html: str) -> list[dict[str, str]]:
    """Parse Glassdoor search result HTML into a list of raw card dicts."""
    cards: list[dict[str, str]] = []
    # Split on known job card boundaries
    card_chunks = re.split(
        r'<li[^>]*class="[^"]*JobsList_jobListItem[^"]*"'
        r'|<div[^>]*data-test="jobListing"',
        page_html,
    )
    for chunk in card_chunks[1:]:  # skip text before first card
        title_match = GLASSDOOR_CARD_TITLE.search(chunk) or GLASSDOOR_CARD_TITLE_ALT.search(chunk)
        company_match = GLASSDOOR_CARD_COMPANY.search(chunk) or GLASSDOOR_CARD_COMPANY_ALT.search(chunk)
        location_match = GLASSDOOR_CARD_LOCATION.search(chunk) or GLASSDOOR_CARD_LOCATION_ALT.search(chunk)
        link_match = GLASSDOOR_CARD_LINK.search(chunk)
        if not title_match:
            continue
        url = ""
        if link_match:
            raw_href = html.unescape(link_match.group(1).strip())
            if raw_href.startswith("/"):
                url = f"https://www.glassdoor.com{raw_href}"
            else:
                url = raw_href
        cards.append({
            "title": _strip_html(title_match.group(1)),
            "company": _strip_html(company_match.group(1)) if company_match else "",
            "location": _strip_html(location_match.group(1)) if location_match else "",
            "url": url,
        })
    return cards




async def fetch_glassdoor_jobs(
    *,
    keywords: list[str] | None = None,
    location: str = "",
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Fetch jobs from Glassdoor using Playwright to bypass anti-bot captchas.

    Launches a headless Chromium browser, navigates to the search page,
    parses HTML job cards, and fetches detail pages for JD text.
    Uses human-like delays between page loads.
    """
    if not keywords:
        return []

    from playwright.async_api import async_playwright

    query_string = " ".join(keywords)
    params: dict[str, str] = {
        "sc.keyword": query_string,
        "locT": "C",
        "locId": "1132348",  # NYC default
    }
    if location:
        params["locKeyword"] = location
    search_url = "https://www.glassdoor.com/Job/jobs.htm?" + urlencode(params)

    jobs: list[dict[str, Any]] = []
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=random.choice(_USER_AGENTS),
                viewport={"width": 1280, "height": 900},
            )
            page = await context.new_page()

            await page.goto(search_url, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_timeout(int(random.uniform(2000, 4000)))

            page_html = await page.content()
            cards = _parse_glassdoor_job_cards(page_html)[:limit]

            for card in cards:
                jobs.append({
                    "title": card["title"],
                    "company": card["company"],
                    "location": card["location"],
                    "url": card["url"],
                    "source": "glassdoor",
                    "jd_text": "",
                    "source_urls": [card["url"]] if card["url"] else [search_url],
                })

            # Fetch detail pages with human-like delays
            for index, job in enumerate(jobs):
                if not job["url"]:
                    continue
                delay = random.uniform(3.0, 6.0) + index * random.uniform(0.3, 0.7)
                if index > 0 and index % 5 == 0:
                    delay += random.uniform(4.0, 8.0)
                await asyncio.sleep(delay)

                try:
                    await page.goto(job["url"], wait_until="domcontentloaded", timeout=25_000)
                    await page.wait_for_timeout(int(random.uniform(1500, 3000)))
                    detail_html = await page.content()
                    jd_text = _extract_glassdoor_jd(detail_html)
                    if jd_text:
                        jobs[index]["jd_text"] = jd_text
                except Exception:
                    continue

            await browser.close()
    except Exception:
        pass

    return jobs


def _extract_glassdoor_jd(page_html: str) -> str:
    """Extract JD text from a Glassdoor detail page."""
    for pattern in GLASSDOOR_JD_PATTERNS:
        match = pattern.search(page_html)
        if match:
            return _strip_html(match.group(1))
    return ""


def _workday_company_name_from_endpoint(endpoint: str) -> str:
    cleaned = str(endpoint or "").strip().rstrip("/")
    if not cleaned:
        return ""
    match = re.search(r"/wday/cxs/([^/]+)/([^/]+)/jobs/?$", cleaned, flags=re.I)
    if match:
        tenant = match.group(1).strip()
        return tenant
    host_match = re.search(r"https?://([^.]+)\.wd\d+\.myworkdayjobs\.com", cleaned, flags=re.I)
    if host_match:
        return host_match.group(1).strip()
    return cleaned


async def fetch_workday_jobs(
    *,
    company: str,
    endpoint: str,
    limit: int = 20,
    search_terms: list[str] | None = None,
) -> list[dict[str, Any]]:
    url = str(endpoint or "").strip()
    if not url:
        return []

    # When no explicit search terms, use role-relevant terms plus a blank
    # search to maximize coverage across different Workday career sites.
    terms_to_try = list(search_terms) if search_terms else ["", "analyst", "data analyst", "business analyst"]
    per_term_limit = max(1, min(int(limit), 20))
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        **REQUEST_HEADERS,
    }

    seen_paths: set[str] = set()
    jobs: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        for search_text in terms_to_try:
            payload = {
                "appliedFacets": {},
                "limit": per_term_limit,
                "offset": 0,
                "searchText": search_text,
            }
            response = await _request_with_retries(client, "POST", url, json=payload, headers=headers)
            if response.status_code in {400, 401, 403, 404, 422, 429, 500, 502, 503}:
                continue
            try:
                response.raise_for_status()
                data = response.json()
            except Exception:
                continue

            for item in data.get("jobPostings", []):
                external_path = str(item.get("externalPath", "") or "").strip()
                dedup_key = external_path or str(item.get("title", "")).strip()
                if dedup_key in seen_paths:
                    continue
                seen_paths.add(dedup_key)

                hosted_url = ""
                if external_path:
                    # Extract site_name from endpoint URL (e.g., "Comcast_Careers" from .../wday/cxs/comcast/Comcast_Careers/jobs)
                    # and insert it before the external_path so the public URL is valid.
                    base = re.sub(r"/wday/cxs/[^/]+/[^/]+/jobs/?$", "", url.rstrip("/"))
                    site_match = re.search(r"/wday/cxs/[^/]+/([^/]+)/jobs/?$", url.rstrip("/"))
                    site_name = site_match.group(1) if site_match else ""
                    if site_name:
                        hosted_url = base + "/" + site_name + external_path
                    else:
                        hosted_url = base + external_path
                description = "\n".join(
                    [
                        str(item.get("title", "") or "").strip(),
                        str(item.get("locationsText", "") or "").strip(),
                        str(item.get("postedOn", "") or "").strip(),
                        " ".join(str(entry).strip() for entry in (item.get("bulletFields") or []) if str(entry).strip()),
                    ]
                ).strip()
                jobs.append(
                    {
                        "title": str(item.get("title", "") or "").strip(),
                        "company": company,
                        "location": str(item.get("locationsText", "") or "").strip(),
                        "url": hosted_url,
                        "source": "workday",
                        "jd_text": description,
                        "source_urls": [hosted_url or url, url],
                        "meta": {
                            "posted_on": str(item.get("postedOn", "") or "").strip(),
                            "external_path": external_path,
                            "bullet_fields": item.get("bulletFields") or [],
                        },
                    }
                )
                if len(jobs) >= limit:
                    break
            if len(jobs) >= limit:
                break

    return jobs
