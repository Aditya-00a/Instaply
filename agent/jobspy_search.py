"""Live job search via JobSpy → populates Instaply SQLite jobs table.

Usage:
    python jobspy_search.py "registered nurse" --location "New York" --limit 30
    python jobspy_search.py "data analyst" --remote --limit 50
    python jobspy_search.py "mechanical engineer" --location "Boston, MA"

This is the offline agent's equivalent of the web app's /jobs/search-live.
Jobs get inserted into jobs.db with status='new' so apply_now.py picks them up.
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from backend.services.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
)
log = logging.getLogger("jobspy_search")


def _stable_id(url: str) -> str:
    return hashlib.sha256((url or "").encode("utf-8")).hexdigest()[:16]


def search_and_insert(
    query: str,
    location: str = "United States",
    limit: int = 30,
    remote: bool = False,
    sites: list[str] | None = None,
) -> int:
    """Run JobSpy search and insert into jobs.db. Returns number of new jobs."""
    try:
        from jobspy import scrape_jobs
    except ImportError:
        log.error("python-jobspy not installed. Run: pip install python-jobspy")
        return 0

    sites = sites or ["indeed", "zip_recruiter", "google"]
    log.info("Searching %s for '%s' in '%s' (limit=%d, remote=%s)",
             ", ".join(sites), query, location, limit, remote)

    kwargs = {
        "site_name": sites,
        "search_term": query,
        "location": location,
        "results_wanted": limit,
        "hours_old": 168,
        "country_indeed": "USA",
        "verbose": 0,
    }
    if remote:
        kwargs["is_remote"] = True

    try:
        df = scrape_jobs(**kwargs)
    except Exception as e:
        log.error("JobSpy scrape failed: %s", e)
        return 0

    if df is None or df.empty:
        log.info("No jobs returned.")
        return 0

    log.info("JobSpy returned %d jobs. Inserting into %s...", len(df), settings.database_path)

    conn = sqlite3.connect(settings.database_path)
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()

    inserted = 0
    skipped = 0
    for _, row in df.iterrows():
        job_url = str(row.get("job_url", "") or "")
        title = str(row.get("title", "") or "")
        company = str(row.get("company", "") or "Unknown")
        location_str = str(row.get("location", "") or "")
        site = str(row.get("site", "") or "unknown")

        if not job_url or not title:
            skipped += 1
            continue

        external_id = f"{site}:{_stable_id(job_url)}"

        try:
            cur.execute("""
                INSERT OR IGNORE INTO jobs (
                    external_id, source, company, title, location, apply_url,
                    status, match_score, discovered_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'new', NULL, ?)
            """, (external_id, site, company, title, location_str, job_url, now))
            if cur.rowcount > 0:
                inserted += 1
        except sqlite3.OperationalError as e:
            # Schema might be different — try alternate column names
            log.warning("Insert failed (schema issue?): %s — trying minimal insert", e)
            try:
                cur.execute("""
                    INSERT OR IGNORE INTO jobs (external_id, title, company, apply_url, status)
                    VALUES (?, ?, ?, ?, 'new')
                """, (external_id, title, company, job_url))
                if cur.rowcount > 0:
                    inserted += 1
            except Exception as e2:
                log.error("Failed: %s", e2)
                skipped += 1

    conn.commit()
    conn.close()
    log.info("Done. Inserted %d new, skipped %d.", inserted, skipped)
    return inserted


def main():
    parser = argparse.ArgumentParser(description="Search jobs live and add to jobs.db")
    parser.add_argument("query", help="Search term (e.g. 'registered nurse')")
    parser.add_argument("--location", default="United States", help="Location filter")
    parser.add_argument("--limit", type=int, default=30, help="Max results")
    parser.add_argument("--remote", action="store_true", help="Remote only")
    parser.add_argument("--sites", default="indeed,zip_recruiter,google",
                        help="Comma-separated sites (indeed, linkedin, zip_recruiter, google, glassdoor)")
    args = parser.parse_args()

    sites = [s.strip() for s in args.sites.split(",")]
    n = search_and_insert(args.query, args.location, args.limit, args.remote, sites)
    print(f"\nInserted {n} new jobs. Run `python apply_now.py` to apply.")


if __name__ == "__main__":
    main()
