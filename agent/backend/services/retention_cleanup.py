from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.db.database import get_connection, init_db
from backend.db.jobs_repository import count_applied_jobs, update_job_status
from backend.services.config import ROOT_DIR, settings

DB_PATH = init_db(Path(settings.database_path))
SAFE_ARTIFACT_ROOT = (ROOT_DIR / "artifacts").resolve()


def _safe_delete(path_text: str) -> bool:
    path_str = str(path_text or "").strip()
    if not path_str:
        return False
    path = Path(path_str)
    try:
        resolved = path.resolve()
    except OSError:
        return False
    if not resolved.exists() or not resolved.is_file():
        return False
    try:
        resolved.relative_to(SAFE_ARTIFACT_ROOT)
    except ValueError:
        return False
    resolved.unlink()
    return True


def _safe_remove_empty_parent_dirs(path_text: str) -> list[str]:
    path_str = str(path_text or "").strip()
    if not path_str:
        return []
    path = Path(path_str)
    try:
        resolved = path.resolve()
    except OSError:
        return []
    removed: list[str] = []
    current = resolved.parent
    while True:
        try:
            current.relative_to(SAFE_ARTIFACT_ROOT)
        except ValueError:
            break
        if current == SAFE_ARTIFACT_ROOT:
            break
        try:
            next(current.iterdir())
            break
        except StopIteration:
            current.rmdir()
            removed.append(str(current))
            current = current.parent
            continue
        except OSError:
            break
    return removed


def cleanup_old_applied_packets(*, keep_latest: int = 20) -> dict[str, Any]:
    with get_connection(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT
              j.id AS job_id,
              j.company,
              j.title,
              j.date_applied,
              j.resume_version,
              j.cover_letter_version,
              rg.pdf_path AS resume_pdf_path,
              rg.docx_path AS resume_docx_path,
              clg.pdf_path AS cover_pdf_path,
              clg.docx_path AS cover_docx_path
            FROM jobs j
            LEFT JOIN resume_generations rg ON rg.id = j.resume_version
            LEFT JOIN cover_letter_generations clg ON clg.id = j.cover_letter_version
            WHERE j.status = 'applied'
            ORDER BY COALESCE(j.date_applied, '') DESC, j.created_at DESC
            """
        ).fetchall()

        rows_list = [dict(row) for row in rows]
        retained = rows_list[:keep_latest]
        to_cleanup = rows_list[keep_latest:]
        deleted_files: list[str] = []
        cleaned_job_ids: list[str] = []

        for row in to_cleanup:
            deleted_any = False
            for path_key in ["resume_pdf_path", "resume_docx_path", "cover_pdf_path", "cover_docx_path"]:
                path_text = str(row.get(path_key) or "").strip()
                if path_text and _safe_delete(path_text):
                    deleted_files.append(path_text)
                    deleted_any = True

            if str(row.get("resume_version") or "").strip():
                conn.execute(
                    "UPDATE resume_generations SET pdf_path = '', docx_path = '' WHERE id = ?",
                    (row["resume_version"],),
                )
            if str(row.get("cover_letter_version") or "").strip():
                conn.execute(
                    "UPDATE cover_letter_generations SET pdf_path = '', docx_path = '' WHERE id = ?",
                    (row["cover_letter_version"],),
                )
            if deleted_any:
                cleaned_job_ids.append(str(row["job_id"]))

        conn.commit()

    return {
        "applied_count": count_applied_jobs(DB_PATH),
        "keep_latest": keep_latest,
        "retained_job_ids": [str(row["job_id"]) for row in retained],
        "cleaned_job_ids": cleaned_job_ids,
        "deleted_files": deleted_files,
        "deleted_file_count": len(deleted_files),
    }


def cleanup_rejected_packets(*, limit: int = 200) -> dict[str, Any]:
    with get_connection(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT
              j.id AS job_id,
              j.company,
              j.title,
              j.resume_version,
              j.cover_letter_version,
              rg.pdf_path AS resume_pdf_path,
              rg.docx_path AS resume_docx_path,
              clg.pdf_path AS cover_pdf_path,
              clg.docx_path AS cover_docx_path
            FROM jobs j
            LEFT JOIN resume_generations rg ON rg.id = j.resume_version
            LEFT JOIN cover_letter_generations clg ON clg.id = j.cover_letter_version
            WHERE j.status = 'rejected'
              AND (
                COALESCE(rg.pdf_path, '') != '' OR
                COALESCE(rg.docx_path, '') != '' OR
                COALESCE(clg.pdf_path, '') != '' OR
                COALESCE(clg.docx_path, '') != ''
              )
            ORDER BY j.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        deleted_files: list[str] = []
        removed_dirs: list[str] = []
        cleaned_job_ids: list[str] = []

        for row in rows:
            row_dict = dict(row)
            paths = [
                str(row_dict.get("resume_pdf_path") or "").strip(),
                str(row_dict.get("resume_docx_path") or "").strip(),
                str(row_dict.get("cover_pdf_path") or "").strip(),
                str(row_dict.get("cover_docx_path") or "").strip(),
            ]
            deleted_any = False
            for path_text in paths:
                if path_text and _safe_delete(path_text):
                    deleted_files.append(path_text)
                    removed_dirs.extend(_safe_remove_empty_parent_dirs(path_text))
                    deleted_any = True

            if str(row_dict.get("resume_version") or "").strip():
                conn.execute(
                    "UPDATE resume_generations SET pdf_path = '', docx_path = '' WHERE id = ?",
                    (row_dict["resume_version"],),
                )
            if str(row_dict.get("cover_letter_version") or "").strip():
                conn.execute(
                    "UPDATE cover_letter_generations SET pdf_path = '', docx_path = '' WHERE id = ?",
                    (row_dict["cover_letter_version"],),
                )
            if deleted_any:
                cleaned_job_ids.append(str(row_dict["job_id"]))

        conn.commit()

    dedup_dirs: list[str] = []
    seen_dirs: set[str] = set()
    for path in removed_dirs:
        if path not in seen_dirs:
            seen_dirs.add(path)
            dedup_dirs.append(path)

    return {
        "cleaned_job_ids": cleaned_job_ids,
        "deleted_files": deleted_files,
        "deleted_file_count": len(deleted_files),
        "removed_dirs": dedup_dirs,
        "removed_dir_count": len(dedup_dirs),
    }


def cleanup_duplicate_active_jobs(*, limit: int = 500) -> dict[str, Any]:
    with get_connection(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT id, title, company, location, status, created_at
            FROM jobs
            WHERE status IN ('new', 'packet_generated', 'reviewed', 'outreach_sent')
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    seen: set[tuple[str, str, str]] = set()
    rejected_job_ids: list[str] = []
    for row in rows:
        job = dict(row)
        key = (
            " ".join(str(job.get("company") or "").strip().lower().split()),
            " ".join(str(job.get("title") or "").strip().lower().split()),
            " ".join(str(job.get("location") or "").strip().lower().split()),
        )
        if key in seen:
            try:
                update_job_status(str(job["id"]), "rejected", DB_PATH)
                rejected_job_ids.append(str(job["id"]))
            except Exception:
                continue
            continue
        seen.add(key)

    return {
        "rejected_job_ids": rejected_job_ids,
        "rejected_count": len(rejected_job_ids),
    }
