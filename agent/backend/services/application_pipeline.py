from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.db.jobs_repository import attach_packet_versions, existing_job_status
from backend.models.job_models import JobRecord
from backend.services.application_packet import generate_application_packet
from backend.services.config import settings
from backend.services.files import load_master_resume, load_profile
from backend.services.job_scout import run_job_scout
from backend.services.tailor import _clean_company_name


FINAL_JOB_STATUSES = {"applied", "outreach_sent", "rejected"}
PACKET_READY_STATUSES = {"packet_generated"}


def _job_sort_key(job: JobRecord) -> tuple[float, int, str]:
    """Sort jobs by match score (primary), visa sponsorship (secondary),
    and date_found (tertiary, newest first) so recent postings are prioritized."""
    sponsorship_bonus = 1 if job.visa_sponsorship_likely else 0
    # date_found is ISO date string — lexicographic sort works (newer = higher)
    return (float(job.match_score), sponsorship_bonus, job.date_found or "")


def _company_context_from_job(job: JobRecord) -> dict[str, Any]:
    return {
        "company": _clean_company_name(job.company),
        "role": job.title,
        "location": job.location,
        "source": job.source,
        "url": job.url,
    }


def _company_background_from_job(job: JobRecord) -> str:
    clean_company = _clean_company_name(job.company)
    reasons = [reason.strip() for reason in job.match_reasons if str(reason).strip()]
    pieces = [
        f"{clean_company} opportunity for {job.title}".strip(),
        f"Location: {job.location}".strip() if job.location else "",
        f"Why it matched: {'; '.join(reasons[:2])}" if reasons else "",
    ]
    return " | ".join(piece for piece in pieces if piece)


def _recipient_lines_from_job(job: JobRecord) -> list[str]:
    company = _clean_company_name(job.company)
    recipient_lines = [company]
    if company:
        recipient_lines.append(f"{company} Recruiting Team")
    return [line for line in recipient_lines if str(line).strip()]


async def discover_rank_generate_packets(
    *,
    greenhouse_companies: list[str] | None = None,
    lever_companies: list[str] | None = None,
    workday_companies: list[str] | None = None,
    ashby_companies: list[str] | None = None,
    jobvite_companies: list[str] | None = None,
    smartrecruiters_companies: list[str] | None = None,
    icims_companies: list[str] | None = None,
    linkedin_keywords: list[str] | None = None,
    linkedin_location: str = "",
    indeed_keywords: list[str] | None = None,
    indeed_location: str = "",
    glassdoor_keywords: list[str] | None = None,
    glassdoor_location: str = "",
    limit_per_source: int = 20,
    max_packets: int = 5,
    output_dir: str | None = None,
    date_text: str = "",
) -> dict[str, Any]:
    profile = load_profile()
    master_resume = load_master_resume()
    scout_result = await run_job_scout(
        greenhouse_companies=greenhouse_companies,
        lever_companies=lever_companies,
        workday_companies=workday_companies,
        ashby_companies=ashby_companies,
        jobvite_companies=jobvite_companies,
        smartrecruiters_companies=smartrecruiters_companies,
        icims_companies=icims_companies,
        linkedin_keywords=linkedin_keywords,
        linkedin_location=linkedin_location,
        indeed_keywords=indeed_keywords,
        indeed_location=indeed_location,
        glassdoor_keywords=glassdoor_keywords,
        glassdoor_location=glassdoor_location,
        limit_per_source=limit_per_source,
        db_path=Path(settings.database_path),
    )

    jobs = sorted(
        scout_result["jobs"],
        key=_job_sort_key,
        reverse=True,
    )

    review_queue: list[dict[str, Any]] = []
    generated_count = 0
    skipped_existing_packets = 0

    for job in jobs:
        status = existing_job_status(job.id, Path(settings.database_path)) or job.status
        if status in FINAL_JOB_STATUSES:
            continue
        if status in PACKET_READY_STATUSES:
            skipped_existing_packets += 1
            continue
        if generated_count >= max_packets:
            break

        packet = generate_application_packet(
            jd_text=job.jd_text,
            profile=profile,
            master_resume=master_resume,
            company_context=_company_context_from_job(job),
            company_background=_company_background_from_job(job),
            output_basename=f"{job.company}_{job.title}_{job.id[:8]}",
            output_dir=output_dir,
            date_text=date_text,
            recipient_lines=_recipient_lines_from_job(job),
        )
        attach_packet_versions(
            job.id,
            resume_generation_id=packet["generation_ids"]["resume"],
            cover_letter_generation_id=packet["generation_ids"]["cover_letter"],
            db_path=Path(settings.database_path),
        )

        review_queue.append(
            {
                "job": job.model_dump(),
                "packet": packet,
            }
        )
        generated_count += 1

    return {
        "company_pool_count": scout_result.get("company_pool_count", 0),
        "company_pool_preview": scout_result.get("company_pool_preview", []),
        "rotating_company_preview": scout_result.get("rotating_company_preview", []),
        "company_rotation_state": scout_result.get("company_rotation_state", {}),
        "company_rotation_start": scout_result.get("company_rotation_start", {}),
        "fetched": scout_result["fetched"],
        "inserted": scout_result["inserted"],
        "skipped": scout_result["skipped"],
        "skipped_companies_due_to_cooldown": scout_result.get("skipped_companies_due_to_cooldown", 0),
        "ranked_jobs": [job.model_dump() for job in jobs],
        "generated_packets": generated_count,
        "skipped_existing_packets": skipped_existing_packets,
        "review_queue": review_queue,
    }
