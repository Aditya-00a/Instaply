from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.db.database import get_connection, init_db
from backend.services.config import ROOT_DIR, settings


PENDING = "pending_approval"
APPROVED = "approved"
DENIED = "denied"
SUBMITTED = "submitted"


def _default_db_path() -> Path:
    configured = Path(settings.database_path)
    if not configured.is_absolute():
        configured = ROOT_DIR / configured
    return init_db(configured)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json_dumps(value: Any) -> str:
    return json.dumps(value or [], ensure_ascii=True)


def _row_to_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    data = dict(row)
    for key in ("filled_fields_json", "needs_review_json"):
        raw = data.get(key)
        try:
            data[key.removesuffix("_json")] = json.loads(raw) if raw else []
        except json.JSONDecodeError:
            data[key.removesuffix("_json")] = []
    return data


def get_review_request(
    review_id: str,
    *,
    db_path: Path | None = None,
) -> dict[str, Any]:
    with get_connection(db_path or _default_db_path()) as conn:
        row = conn.execute(
            """
            SELECT r.*, j.company, j.title, j.url, j.match_score
            FROM application_review_requests r
            JOIN jobs j ON j.id = r.job_id
            WHERE r.id = ?
            """,
            (review_id,),
        ).fetchone()
    return _row_to_dict(row)


def create_or_update_review_request(
    *,
    job_id: str,
    screenshot_path: str,
    platform: str = "",
    filled_fields: list[str] | None = None,
    needs_review: list[dict[str, str]] | None = None,
    post_submit_screenshot_path: str = "",
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Persist the human approval gate for a filled application.

    A job can have only one open approval request. Re-running fill refreshes
    the screenshot and field evidence instead of creating duplicates.
    """
    now = _now_iso()
    with get_connection(db_path or _default_db_path()) as conn:
        existing = conn.execute(
            """
            SELECT id
            FROM application_review_requests
            WHERE job_id = ? AND status = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (job_id, PENDING),
        ).fetchone()
        if existing:
            review_id = existing["id"]
            conn.execute(
                """
                UPDATE application_review_requests
                SET screenshot_path = ?,
                    post_submit_screenshot_path = ?,
                    platform = ?,
                    filled_fields_json = ?,
                    needs_review_json = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    screenshot_path,
                    post_submit_screenshot_path,
                    platform,
                    _json_dumps(filled_fields),
                    _json_dumps(needs_review),
                    now,
                    review_id,
                ),
            )
        else:
            review_id = uuid4().hex
            conn.execute(
                """
                INSERT INTO application_review_requests (
                  id, job_id, status, screenshot_path, post_submit_screenshot_path,
                  platform, filled_fields_json, needs_review_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    job_id,
                    PENDING,
                    screenshot_path,
                    post_submit_screenshot_path,
                    platform,
                    _json_dumps(filled_fields),
                    _json_dumps(needs_review),
                    now,
                    now,
                ),
            )
        conn.commit()
        row = conn.execute(
            """
            SELECT r.*, j.company, j.title, j.url
            FROM application_review_requests r
            JOIN jobs j ON j.id = r.job_id
            WHERE r.id = ?
            """,
            (review_id,),
        ).fetchone()
    return _row_to_dict(row)


def record_review_decision(
    review_id: str,
    *,
    decision: str,
    notes: str = "",
    db_path: Path | None = None,
) -> dict[str, Any]:
    normalized = str(decision or "").strip().lower()
    if normalized not in {APPROVED, DENIED}:
        raise ValueError("decision must be 'approved' or 'denied'")
    now = _now_iso()
    with get_connection(db_path or _default_db_path()) as conn:
        existing = conn.execute(
            "SELECT id FROM application_review_requests WHERE id = ?",
            (review_id,),
        ).fetchone()
        if not existing:
            raise ValueError(f"review request not found: {review_id}")
        conn.execute(
            """
            UPDATE application_review_requests
            SET status = ?,
                decision = ?,
                decision_notes = ?,
                decided_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (normalized, normalized, notes, now, now, review_id),
        )
        conn.commit()
        row = conn.execute(
            """
            SELECT r.*, j.company, j.title, j.url
            FROM application_review_requests r
            JOIN jobs j ON j.id = r.job_id
            WHERE r.id = ?
            """,
            (review_id,),
        ).fetchone()
    return _row_to_dict(row)


def mark_review_submitted(
    review_id: str,
    *,
    post_submit_screenshot_path: str = "",
    notes: str = "",
    db_path: Path | None = None,
) -> dict[str, Any]:
    now = _now_iso()
    with get_connection(db_path or _default_db_path()) as conn:
        existing = conn.execute(
            "SELECT id FROM application_review_requests WHERE id = ?",
            (review_id,),
        ).fetchone()
        if not existing:
            raise ValueError(f"review request not found: {review_id}")
        conn.execute(
            """
            UPDATE application_review_requests
            SET status = ?,
                post_submit_screenshot_path = COALESCE(NULLIF(?, ''), post_submit_screenshot_path),
                decision_notes = CASE
                    WHEN ? = '' THEN decision_notes
                    WHEN decision_notes IS NULL OR decision_notes = '' THEN ?
                    ELSE decision_notes || CHAR(10) || ?
                END,
                updated_at = ?
            WHERE id = ?
            """,
            (SUBMITTED, post_submit_screenshot_path, notes, notes, notes, now, review_id),
        )
        conn.commit()
    return get_review_request(review_id, db_path=db_path)


def list_review_requests(
    *,
    status: str = PENDING,
    limit: int = 20,
    db_path: Path | None = None,
) -> dict[str, Any]:
    with get_connection(db_path or _default_db_path()) as conn:
        rows = conn.execute(
            """
            SELECT r.*, j.company, j.title, j.url, j.match_score
            FROM application_review_requests r
            JOIN jobs j ON j.id = r.job_id
            WHERE r.status = ?
            ORDER BY r.updated_at DESC
            LIMIT ?
            """,
            (status, limit),
        ).fetchall()
    items = [_row_to_dict(row) for row in rows]
    return {"count": len(items), "items": items}
