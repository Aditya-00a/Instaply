from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from backend.db.database import get_connection
from backend.services.config import settings
from backend.services.files import load_profile
from backend.services.matcher import match_job

logger = logging.getLogger(__name__)


def rescore_all_jobs(min_old_score: float = 0.0) -> dict[str, Any]:
    """Re-score every job in the DB using the current matcher logic.

    Returns a summary dict with *rescored_count* and *score_changes* list.
    Jobs whose status is already ``rejected`` or ``applied`` are still
    re-scored (the score column is updated) but their status is **not**
    changed.  For other statuses, if the new score falls below the
    profile's ``min_match_score`` the job is moved to ``rejected``.
    """
    profile = load_profile()
    min_match_score: float = profile.get("min_match_score", 0.72)
    db_path = Path(settings.database_path)

    score_changes: list[dict[str, Any]] = []

    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, title, company, location, url, jd_text, match_score, status
            FROM jobs
            WHERE match_score >= ?
            """,
            (min_old_score,),
        ).fetchall()

        for row in rows:
            jd_text = row["jd_text"]
            if not jd_text:
                continue

            result = match_job(
                jd_text,
                profile,
                title=row["title"] or "",
                location=row["location"] or "",
                company=row["company"] or "",
                url=row["url"] or "",
            )
            new_score = result["match_score"]
            old_score = row["match_score"] if row["match_score"] is not None else 0.0

            if new_score == old_score:
                continue

            # Always update the score column
            conn.execute(
                "UPDATE jobs SET match_score = ? WHERE id = ?",
                (new_score, row["id"]),
            )

            score_changes.append(
                {
                    "job_id": row["id"],
                    "title": row["title"],
                    "company": row["company"],
                    "old_score": round(old_score, 4),
                    "new_score": round(new_score, 4),
                }
            )

            # Transition to rejected if below threshold (skip already-terminal statuses)
            current_status = row["status"] or "new"
            if (
                new_score < min_match_score
                and current_status not in ("rejected", "applied", "outreach_sent")
            ):
                conn.execute(
                    "UPDATE jobs SET status = ? WHERE id = ?",
                    ("rejected", row["id"]),
                )
                conn.execute(
                    """
                    INSERT INTO job_status_events (id, job_id, from_status, to_status, reason)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        row["id"],
                        current_status,
                        "rejected",
                        f"rescore: {old_score:.4f} -> {new_score:.4f} (below {min_match_score})",
                    ),
                )

        conn.commit()

    logger.info("Rescore complete: %d jobs updated", len(score_changes))
    return {
        "rescored_count": len(score_changes),
        "score_changes": score_changes,
    }
