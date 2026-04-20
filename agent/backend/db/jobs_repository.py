from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.db.database import get_connection
from backend.models.job_models import JobRecord

ALLOWED_JOB_TRANSITIONS = {
    "new": {"scored", "packet_generated", "rejected"},
    "scored": {"packet_generated", "rejected"},
    "packet_generated": {"reviewed", "applied", "rejected"},
    "reviewed": {"packet_generated", "applied", "rejected"},
    "applied": {"outreach_sent", "rejected"},
    "outreach_sent": {"rejected"},
    "rejected": {"new"},  # allow retry after reset
}


def utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def normalize_text(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def dedup_key(company: str, title: str, location: str) -> str:
    base = f"{normalize_text(company)}|{normalize_text(title)}|{normalize_text(location)}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def existing_job_status(key: str, db_path: Path | None = None) -> str | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT status FROM jobs WHERE id = ? LIMIT 1",
            (key,),
        ).fetchone()
        return row["status"] if row else None


def _record_status_event(job_id: str, from_status: str | None, to_status: str, reason: str = "", db_path: Path | None = None) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO job_status_events (id, job_id, from_status, to_status, reason)
            VALUES (?, ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), job_id, from_status, to_status, reason),
        )
        conn.commit()


def transition_job_status(job_id: str, to_status: str, *, reason: str = "", db_path: Path | None = None) -> None:
    current_status = existing_job_status(job_id, db_path)
    if current_status is None:
        raise ValueError(f"Unknown job_id: {job_id}")
    if current_status == to_status:
        return
    allowed = ALLOWED_JOB_TRANSITIONS.get(current_status, set())
    if to_status not in allowed:
        raise ValueError(f"Invalid job status transition: {current_status} -> {to_status}")

    with get_connection(db_path) as conn:
        if to_status == "applied":
            conn.execute(
                "UPDATE jobs SET status = ?, date_applied = ? WHERE id = ?",
                (to_status, utc_today(), job_id),
            )
        else:
            conn.execute(
                "UPDATE jobs SET status = ? WHERE id = ?",
                (to_status, job_id),
            )
        conn.execute(
            """
            INSERT INTO job_status_events (id, job_id, from_status, to_status, reason)
            VALUES (?, ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), job_id, current_status, to_status, reason),
        )
        conn.commit()


def upsert_job(job: JobRecord, db_path: Path | None = None) -> bool:
    existing_status = existing_job_status(job.id, db_path)
    if existing_status in {"applied", "outreach_sent", "rejected"}:
        return False

    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO jobs (
              id, title, company, location, url, source, jd_text, match_score,
              status, date_found, source_urls_json, visa_sponsorship_likely
              , visa_sponsorship_blocked
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              url = excluded.url,
              source = excluded.source,
              jd_text = excluded.jd_text,
              match_score = excluded.match_score,
              source_urls_json = excluded.source_urls_json,
              visa_sponsorship_likely = excluded.visa_sponsorship_likely,
              visa_sponsorship_blocked = excluded.visa_sponsorship_blocked
            """,
            (
                job.id,
                job.title,
                job.company,
                job.location,
                job.url,
                job.source,
                job.jd_text,
                job.match_score,
                job.status,
                job.date_found or utc_today(),
                json.dumps(job.source_urls),
                int(job.visa_sponsorship_likely),
                int(job.visa_sponsorship_blocked),
            ),
        )
        conn.commit()
    if existing_status is None:
        _record_status_event(job.id, None, job.status, "job_discovered", db_path)
    return True


def make_job_id(company: str, title: str, location: str) -> str:
    return dedup_key(company, title, location)


def make_resume_version_id() -> str:
    return str(uuid.uuid4())


def attach_packet_versions(
    job_id: str,
    *,
    resume_generation_id: str,
    cover_letter_generation_id: str,
    db_path: Path | None = None,
) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE jobs
            SET
              resume_version = ?,
              cover_letter_version = ?
            WHERE id = ?
            """,
            (resume_generation_id, cover_letter_generation_id, job_id),
        )
        conn.commit()
    transition_job_status(job_id, "packet_generated", reason="application_packet_generated", db_path=db_path)


def update_job_status(job_id: str, status: str, db_path: Path | None = None) -> None:
    transition_job_status(job_id, status, reason="manual_status_update", db_path=db_path)


def mark_job_applied(job_id: str, db_path: Path | None = None) -> None:
    transition_job_status(job_id, "applied", reason="application_submitted", db_path=db_path)


def mark_job_outreach_sent(job_id: str, db_path: Path | None = None) -> None:
    transition_job_status(job_id, "outreach_sent", reason="outreach_sent", db_path=db_path)


def mark_job_rejected(job_id: str, db_path: Path | None = None) -> None:
    transition_job_status(job_id, "rejected", reason="job_rejected", db_path=db_path)


def count_company_active_jobs(company: str, db_path: Path | None = None) -> int:
    """Count jobs at a company that are applied, packet_generated, or outreach_sent."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM jobs WHERE LOWER(company) = LOWER(?) AND status IN ('applied', 'packet_generated', 'outreach_sent')",
            (company.strip(),),
        ).fetchone()
    return int(row["cnt"]) if row else 0


def has_applied_to_title(company: str, title: str, db_path: Path | None = None) -> bool:
    """Check if we've already applied/generated packet for the same company+title (any location)."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM jobs WHERE LOWER(company) = LOWER(?) AND LOWER(title) = LOWER(?) AND status IN ('applied', 'packet_generated', 'outreach_sent') LIMIT 1",
            (company.strip(), title.strip()),
        ).fetchone()
    return row is not None


def count_applied_jobs(db_path: Path | None = None) -> int:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS applied_count FROM jobs WHERE status = 'applied'"
        ).fetchone()
    return int(row["applied_count"]) if row else 0


def get_job_status_history(job_id: str, db_path: Path | None = None) -> list[dict[str, str]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT from_status, to_status, reason, created_at
            FROM job_status_events
            WHERE job_id = ?
            ORDER BY created_at ASC
            """,
            (job_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _source_scan_key(source: str, company: str) -> str:
    base = f"{normalize_text(source)}|{normalize_text(company)}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def company_source_scanned_recently(
    company: str,
    source: str,
    *,
    cooldown_days: int = 3,
    db_path: Path | None = None,
) -> bool:
    if int(cooldown_days or 0) <= 0:
        return False
    cutoff = (datetime.now(timezone.utc) - timedelta(days=cooldown_days)).isoformat()
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT scanned_at
            FROM source_scan_history
            WHERE source = ? AND company = ? AND scanned_at >= ?
            ORDER BY scanned_at DESC
            LIMIT 1
            """,
            (normalize_text(source), normalize_text(company), cutoff),
        ).fetchone()
    return row is not None


def record_company_source_scan(
    company: str,
    source: str,
    *,
    source_url: str = "",
    db_path: Path | None = None,
) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO source_scan_history (id, source, company, source_url, scanned_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              source_url = excluded.source_url,
              scanned_at = excluded.scanned_at
            """,
            (
                _source_scan_key(source, company),
                normalize_text(source),
                normalize_text(company),
                source_url,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
