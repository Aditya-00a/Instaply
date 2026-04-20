from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = ROOT_DIR / "data" / "jobs.db"
SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _run_migrations(conn: sqlite3.Connection) -> None:
    table_names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "cover_letter_feedback" in table_names:
        _ensure_column(conn, "cover_letter_feedback", "kept_projects_json", "TEXT")
        _ensure_column(conn, "cover_letter_feedback", "removed_projects_json", "TEXT")
    if "jobs" in table_names:
        _ensure_column(conn, "jobs", "visa_sponsorship_blocked", "INTEGER DEFAULT 0")
    if "email_threads" in table_names:
        _ensure_column(conn, "email_threads", "updated_at", "TEXT DEFAULT CURRENT_TIMESTAMP")
    if "processed_email_replies" in table_names:
        _ensure_column(conn, "processed_email_replies", "parsed_commands_json", "TEXT")
        _ensure_column(conn, "processed_email_replies", "applied_result_json", "TEXT")
    if "agent_runtime_state" in table_names:
        _ensure_column(conn, "agent_runtime_state", "agent_enabled", "INTEGER DEFAULT 1")
    if "application_tracking" in table_names:
        _ensure_column(conn, "application_tracking", "rejected_at", "TEXT")
        _ensure_column(conn, "application_tracking", "rejection_source", "TEXT")  # email, portal, ats_auto
        _ensure_column(conn, "application_tracking", "hours_to_rejection", "REAL")
    if "application_answers" in table_names:
        _ensure_column(conn, "application_answers", "control_kind", "TEXT")
        _ensure_column(conn, "application_answers", "answer_source", "TEXT DEFAULT 'rule'")
        _ensure_column(conn, "application_answers", "confidence", "REAL DEFAULT 0.7")
        _ensure_column(conn, "application_answers", "active", "INTEGER DEFAULT 1")
        _ensure_column(conn, "application_answers", "updated_at", "TEXT DEFAULT CURRENT_TIMESTAMP")
    if "career_site_discovery" in table_names:
        _ensure_column(conn, "career_site_discovery", "official_domain", "TEXT")
        _ensure_column(conn, "career_site_discovery", "careers_url", "TEXT")
        _ensure_column(conn, "career_site_discovery", "ats_provider", "TEXT")
        _ensure_column(conn, "career_site_discovery", "ats_target", "TEXT")
        _ensure_column(conn, "career_site_discovery", "source_url", "TEXT")
        _ensure_column(conn, "career_site_discovery", "status", "TEXT DEFAULT 'active'")
        _ensure_column(conn, "career_site_discovery", "confidence", "REAL DEFAULT 0.6")
        _ensure_column(conn, "career_site_discovery", "updated_at", "TEXT DEFAULT CURRENT_TIMESTAMP")


def init_db(db_path: Path | None = None) -> Path:
    path = db_path or DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        _run_migrations(conn)
        conn.commit()
    return path


@contextmanager
def get_connection(db_path: Path | None = None):
    path = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
