"""Generate packet + apply immediately for each job, one at a time.

Usage: python apply_now.py [--max N] [--source workday] [--min-score 0.70]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sqlite3
import sys
from pathlib import Path

# Project root
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from backend.db.jobs_repository import attach_packet_versions
from backend.services.application_packet import generate_application_packet
from backend.services.application_pipeline import (
    _company_background_from_job,
    _company_context_from_job,
    _recipient_lines_from_job,
)
from backend.services.auto_apply import auto_apply_batch
from backend.services.config import settings
from backend.services.files import load_master_resume, load_profile
from backend.models.job_models import JobRecord

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(ROOT / "artifacts" / "apply_now.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("apply_now")


def _load_jobs(source_filter: str | None, min_score: float, max_jobs: int) -> list[dict]:
    """Load top-scoring new/scored jobs from DB."""
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    query = """
        SELECT * FROM jobs
        WHERE status IN ('new', 'scored')
        AND match_score >= ?
    """
    params: list = [min_score]

    if source_filter:
        if source_filter == "workday":
            query += " AND (url LIKE '%workday%' OR url LIKE '%myworkday%')"
        else:
            query += " AND source = ?"
            params.append(source_filter)

    query += " ORDER BY match_score DESC LIMIT ?"
    params.append(max_jobs)

    rows = c.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _row_to_job_record(row: dict) -> JobRecord:
    """Convert a DB row dict to a JobRecord."""
    return JobRecord(
        id=row["id"],
        title=row["title"],
        company=row["company"],
        location=row.get("location", ""),
        url=row["url"],
        source=row.get("source", ""),
        jd_text=row.get("jd_text", ""),
        match_score=float(row.get("match_score", 0)),
        status=row.get("status", "new"),
        date_found=row.get("date_found", ""),
        visa_sponsorship_likely=bool(row.get("visa_sponsorship_likely", False)),
        match_reasons=[],
    )


def _generate_packet(job: JobRecord, profile: dict, master_resume: dict) -> dict | None:
    """Generate resume + cover letter packet for a job."""
    try:
        packet = generate_application_packet(
            jd_text=job.jd_text,
            profile=profile,
            master_resume=master_resume,
            company_context=_company_context_from_job(job),
            company_background=_company_background_from_job(job),
            output_basename=f"{job.company}_{job.title}_{job.id[:8]}",
        )
        attach_packet_versions(
            job.id,
            resume_generation_id=packet["generation_ids"]["resume"],
            cover_letter_generation_id=packet["generation_ids"]["cover_letter"],
            db_path=Path(settings.database_path),
        )
        return packet
    except Exception as e:
        log.error("Packet generation failed for %s at %s: %s", job.title, job.company, e)
        return None


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=25, help="Max jobs to process")
    parser.add_argument("--source", type=str, default=None, help="Filter by source (workday, greenhouse, lever)")
    parser.add_argument("--min-score", type=float, default=0.65, help="Minimum match score")
    args = parser.parse_args()

    log.info("=" * 60)
    log.info("APPLY NOW — generate packet + apply immediately")
    log.info("  Source filter: %s", args.source or "all")
    log.info("  Min score: %.2f", args.min_score)
    log.info("  Max jobs: %d", args.max)
    log.info("=" * 60)

    jobs_data = _load_jobs(args.source, args.min_score, args.max)
    if not jobs_data:
        log.info("No jobs found matching criteria")
        return

    log.info("Found %d jobs to process", len(jobs_data))

    profile = load_profile()
    master_resume = load_master_resume()

    applied = 0
    failed = 0

    for i, row in enumerate(jobs_data, 1):
        job = _row_to_job_record(row)
        log.info("-" * 50)
        log.info("[%d/%d] %s at %s (score=%.2f)", i, len(jobs_data), job.title, job.company, job.match_score)
        log.info("  URL: %s", job.url)

        # Step 1: Generate packet
        log.info("  Generating packet...")
        packet = _generate_packet(job, profile, master_resume)
        if not packet:
            failed += 1
            continue
        log.info("  ✓ Packet ready — applying now...")

        # Step 2: Apply immediately (batch of 1 — only this job is packet_generated)
        try:
            result = await auto_apply_batch(min_score=0.0, limit=1)
            batch_applied = result.get("applied_count", 0)
            if batch_applied > 0:
                applied += 1
                log.info("  ✓ APPLIED to %s at %s!", job.title, job.company)
            else:
                failed += 1
                reasons = [r.get("reason", r.get("status", "?")) for r in result.get("results", [])]
                log.warning("  ✗ Apply result: %s", reasons)
        except Exception as e:
            failed += 1
            log.error("  ✗ Apply failed: %s", e)

    log.info("=" * 60)
    log.info("DONE — Applied: %d, Failed: %d, Total: %d", applied, failed, len(jobs_data))
    log.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
