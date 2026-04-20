"""Application tracking service.

Tracks job applications through their lifecycle:
ready -> applied -> response_received -> interviewing -> offer | rejected | ghosted | withdrawn
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from uuid import uuid4

from backend.db.database import get_connection

TERMINAL_STATUSES = {"offer", "rejected", "ghosted", "withdrawn"}
VALID_STATUSES = {"ready", "applied", "response_received", "interviewing"} | TERMINAL_STATUSES
MAX_FOLLOWUPS = 3
FOLLOWUP_INTERVAL_DAYS = 7


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def _now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _date_plus_days(iso_date: str, days: int) -> str:
    dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
    return (dt + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def track_application(job_id: str, applied_via: str = "", notes: str = "") -> dict:
    """Create a tracking record when you apply to a job."""
    tracking_id = uuid4().hex
    now = _now_iso()
    applied_at = now
    followup_due_at = _date_plus_days(now, FOLLOWUP_INTERVAL_DAYS)

    with get_connection() as conn:
        # Verify job exists
        job = conn.execute("SELECT id, company, title FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not job:
            return {"error": f"Job {job_id} not found"}

        # Check for existing tracking
        existing = conn.execute(
            "SELECT id FROM application_tracking WHERE job_id = ?", (job_id,)
        ).fetchone()
        if existing:
            return {"error": f"Tracking already exists for job {job_id}", "tracking_id": existing["id"]}

        conn.execute(
            """INSERT INTO application_tracking
               (id, job_id, status, applied_at, applied_via, followup_due_at, notes, created_at, updated_at)
               VALUES (?, ?, 'applied', ?, ?, ?, ?, ?, ?)""",
            (tracking_id, job_id, applied_at, applied_via, followup_due_at, notes, now, now),
        )
        conn.commit()

        row = conn.execute(
            "SELECT t.*, j.title, j.company FROM application_tracking t JOIN jobs j ON t.job_id = j.id WHERE t.id = ?",
            (tracking_id,),
        ).fetchone()

    return {"tracking": _row_to_dict(row)}


def update_tracking(tracking_id: str, **fields) -> dict:
    """Update any tracking fields (response, interview, offer, outcome)."""
    allowed_fields = {
        "status", "response_type", "response_received_at", "interview_scheduled_at",
        "interview_notes", "offer_received_at", "offer_details", "outcome", "notes",
        "followup_due_at", "followup_count", "last_followup_at",
    }
    updates = {k: v for k, v in fields.items() if k in allowed_fields and v is not None}

    if not updates:
        return {"error": "No valid fields to update"}

    if "status" in updates and updates["status"] not in VALID_STATUSES:
        return {"error": f"Invalid status: {updates['status']}. Valid: {VALID_STATUSES}"}

    updates["updated_at"] = _now_iso()

    # Auto-set timestamps based on status transitions
    status = updates.get("status")
    if status == "response_received" and "response_received_at" not in updates:
        updates["response_received_at"] = _now_iso()
    if status == "offer" and "offer_received_at" not in updates:
        updates["offer_received_at"] = _now_iso()

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [tracking_id]

    with get_connection() as conn:
        conn.execute(f"UPDATE application_tracking SET {set_clause} WHERE id = ?", values)
        conn.commit()

        row = conn.execute(
            "SELECT t.*, j.title, j.company FROM application_tracking t JOIN jobs j ON t.job_id = j.id WHERE t.id = ?",
            (tracking_id,),
        ).fetchone()

    if not row:
        return {"error": f"Tracking record {tracking_id} not found"}

    return {"tracking": _row_to_dict(row)}


def list_applications(status: str | None = None, limit: int = 50) -> dict:
    """List all tracked applications with job details."""
    query = """
        SELECT t.*, j.title, j.company, j.url, j.match_score
        FROM application_tracking t
        JOIN jobs j ON t.job_id = j.id
    """
    params: list = []

    if status:
        query += " WHERE t.status = ?"
        params.append(status)

    query += " ORDER BY t.updated_at DESC LIMIT ?"
    params.append(limit)

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()

    items = [_row_to_dict(r) for r in rows]
    return {"count": len(items), "items": items}


def get_followups_due() -> dict:
    """Get applications needing follow-up (followup_due_at <= today, not terminal)."""
    now = _now_iso()
    placeholders = ", ".join("?" for _ in TERMINAL_STATUSES)

    with get_connection() as conn:
        rows = conn.execute(
            f"""SELECT t.*, j.title, j.company, j.url
                FROM application_tracking t
                JOIN jobs j ON t.job_id = j.id
                WHERE t.followup_due_at <= ?
                  AND t.followup_due_at IS NOT NULL
                  AND t.status NOT IN ({placeholders})
                ORDER BY t.followup_due_at ASC""",
            [now] + sorted(TERMINAL_STATUSES),
        ).fetchall()

    items = [_row_to_dict(r) for r in rows]
    return {"count": len(items), "items": items}


def schedule_followup(tracking_id: str, followup_date: str, notes: str = "") -> dict:
    """Schedule a follow-up for a tracking record."""
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM application_tracking WHERE id = ?", (tracking_id,)).fetchone()
        if not row:
            return {"error": f"Tracking record {tracking_id} not found"}

        current = _row_to_dict(row)
        current_count = current.get("followup_count") or 0

        if current_count >= MAX_FOLLOWUPS:
            return {
                "error": f"Max follow-ups ({MAX_FOLLOWUPS}) reached for this application",
                "followup_count": current_count,
            }

        now = _now_iso()
        new_count = current_count + 1
        update_notes = current.get("notes") or ""
        if notes:
            update_notes = f"{update_notes}\n[Followup #{new_count}] {notes}".strip()

        conn.execute(
            """UPDATE application_tracking
               SET followup_due_at = ?, followup_count = ?, last_followup_at = ?,
                   notes = ?, updated_at = ?
               WHERE id = ?""",
            (followup_date, new_count, now, update_notes, now, tracking_id),
        )

        # Auto-schedule next followup if under max
        next_followup = None
        if new_count < MAX_FOLLOWUPS:
            next_followup = _date_plus_days(followup_date, FOLLOWUP_INTERVAL_DAYS)

        conn.commit()

        updated = conn.execute(
            "SELECT t.*, j.title, j.company FROM application_tracking t JOIN jobs j ON t.job_id = j.id WHERE t.id = ?",
            (tracking_id,),
        ).fetchone()

    result = {"tracking": _row_to_dict(updated)}
    if next_followup:
        result["next_suggested_followup"] = next_followup
    return result


def get_application_stats() -> dict:
    """Aggregate stats: total applied, response rate, interview rate, offer rate, by source, by company."""
    with get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) as c FROM application_tracking").fetchone()["c"]

        status_counts_rows = conn.execute(
            "SELECT status, COUNT(*) as c FROM application_tracking GROUP BY status"
        ).fetchall()
        status_counts = {r["status"]: r["c"] for r in status_counts_rows}

        by_source_rows = conn.execute(
            "SELECT applied_via, COUNT(*) as c FROM application_tracking WHERE applied_via IS NOT NULL AND applied_via != '' GROUP BY applied_via ORDER BY c DESC"
        ).fetchall()
        by_source = {r["applied_via"]: r["c"] for r in by_source_rows}

        by_company_rows = conn.execute(
            """SELECT j.company, COUNT(*) as c,
                      SUM(CASE WHEN t.status IN ('response_received','interviewing','offer') THEN 1 ELSE 0 END) as responded,
                      SUM(CASE WHEN t.status = 'offer' THEN 1 ELSE 0 END) as offers
               FROM application_tracking t JOIN jobs j ON t.job_id = j.id
               GROUP BY j.company ORDER BY c DESC LIMIT 20"""
        ).fetchall()
        by_company = [_row_to_dict(r) for r in by_company_rows]

    applied = total
    responded = status_counts.get("response_received", 0) + status_counts.get("interviewing", 0) + status_counts.get("offer", 0)
    interviewed = status_counts.get("interviewing", 0) + status_counts.get("offer", 0)
    offers = status_counts.get("offer", 0)

    return {
        "stats": {
            "total_applied": applied,
            "response_rate": round(responded / applied, 3) if applied else 0,
            "interview_rate": round(interviewed / applied, 3) if applied else 0,
            "offer_rate": round(offers / applied, 3) if applied else 0,
            "status_breakdown": status_counts,
            "by_source": by_source,
            "by_company": by_company,
        }
    }
