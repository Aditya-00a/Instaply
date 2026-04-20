"""Local SQLite store for the Instaply MCP server.

Single-file database at `~/.instaply/data.db` (override with the
INSTAPLY_DATA_DIR env var). No network, no Supabase, no auth — the
user owns their data. This is what makes the MCP server zero-
maintenance: if the original author disappears tomorrow, every
existing install keeps working forever because nothing depends on a
remote service the author has to keep alive.

Schema is intentionally tiny and pragmatic:

  profile         — single-row key/value blob for the user's identity
                    (full_name, email, phone, linkedin_url, etc.)
  answers         — per-(question_hash) saved answer for the
                    answer-vault reuse pattern
  applications    — local history of jobs the agent has acted on,
                    with status + audit trail
  jobs            — local cache of discovered jobs (so list/search
                    don't hit the network on every call)

When the worker port lands in a follow-up turn, the autofill engine
talks to this same SQLite store via the helpers below. Nothing else
in the architecture changes.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional


def _data_dir() -> Path:
    """Resolve the per-user Instaply data directory.

    Override via INSTAPLY_DATA_DIR (handy for tests). Otherwise lives
    under the user's home so it survives uvx reinstalls and works the
    same on macOS/Linux/Windows.
    """
    override = os.environ.get("INSTAPLY_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".instaply"


def _db_path() -> Path:
    d = _data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / "data.db"


# ─── Connection + schema ─────────────────────────────────────────
_SCHEMA = """
CREATE TABLE IF NOT EXISTS profile (
    -- single-row table; PK forces upsert semantics
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    data            TEXT NOT NULL DEFAULT '{}',  -- JSON blob; flexible schema
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS answers (
    -- mirrors the worker's answer-vault contract; question_hash is the
    -- normalized-then-sha256 of the question text. See
    -- worker/autofill/cache.py for the canonical normalization the MCP
    -- worker port will share once it lands.
    id              TEXT PRIMARY KEY,            -- uuid4 hex
    question_hash   TEXT NOT NULL UNIQUE,
    question_text   TEXT NOT NULL,
    answer_text     TEXT NOT NULL,
    times_used      INTEGER NOT NULL DEFAULT 0,
    last_used_at    TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS answers_last_used_idx ON answers (last_used_at DESC);

CREATE TABLE IF NOT EXISTS jobs (
    -- local cache of discovered jobs so list / search don't
    -- re-scrape on every call. Dedup by (source, external_id).
    id              TEXT PRIMARY KEY,            -- uuid4 hex
    source          TEXT NOT NULL,
    external_id     TEXT NOT NULL,
    company_name    TEXT,
    title           TEXT,
    location        TEXT,
    apply_url       TEXT NOT NULL,
    description     TEXT,
    discovered_at   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (source, external_id)
);
CREATE INDEX IF NOT EXISTS jobs_discovered_idx ON jobs (discovered_at DESC);

CREATE TABLE IF NOT EXISTS applications (
    -- the agent's record of what it acted on. Mirrors the hosted
    -- product's `applications` table at the level of detail the
    -- single-user, local case actually needs.
    id              TEXT PRIMARY KEY,            -- uuid4 hex
    job_id          TEXT NOT NULL REFERENCES jobs (id) ON DELETE CASCADE,
    status          TEXT NOT NULL,
    submission_log  TEXT,                        -- JSON
    error_message   TEXT,
    queued_at       TEXT NOT NULL DEFAULT (datetime('now')),
    started_at      TEXT,
    completed_at    TEXT,
    UNIQUE (job_id)                              -- one application per job
);
CREATE INDEX IF NOT EXISTS applications_status_idx ON applications (status);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Open a connection with sane defaults + ensure the schema exists.

    Foreign keys ON, row factory dict-like, WAL mode for fewer write
    locks. Caller-managed transaction (use `with conn:` to commit).
    """
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        conn.executescript(_SCHEMA)
        yield conn
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row | None) -> Optional[dict[str, Any]]:
    return dict(row) if row is not None else None


# ─── Question hash (mirrors worker/autofill/cache.py) ───────────
def _normalize_question(text: str) -> str:
    """Mirror of worker.autofill.cache.question_hash normalization.

    Lowercase, collapse internal whitespace, strip leading/trailing
    non-word characters. MUST stay byte-identical to the worker so
    answers saved here can be looked up by the worker (and vice
    versa) once the worker port lands.
    """
    s = (text or "").lower().strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"^[\W_]+|[\W_]+$", "", s)
    return s


def question_hash(text: str) -> str:
    return hashlib.sha256(_normalize_question(text).encode("utf-8")).hexdigest()


# ─── Profile ────────────────────────────────────────────────────
def get_profile() -> dict[str, Any]:
    with connect() as c:
        row = c.execute("SELECT data FROM profile WHERE id = 1").fetchone()
        if not row:
            return {}
        try:
            return json.loads(row["data"]) or {}
        except json.JSONDecodeError:
            return {}


def update_profile(patch: dict[str, Any]) -> dict[str, Any]:
    """Merge `patch` into the stored profile (sparse update). Empty
    string values are kept; explicit None deletes the key."""
    current = get_profile()
    for k, v in patch.items():
        if v is None:
            current.pop(k, None)
        else:
            current[k] = v
    with connect() as c, c:
        c.execute(
            "INSERT INTO profile (id, data, updated_at) VALUES (1, ?, datetime('now')) "
            "ON CONFLICT(id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
            (json.dumps(current),),
        )
    return current


# ─── Answer vault ───────────────────────────────────────────────
def save_answer(question: str, answer: str) -> dict[str, Any]:
    import uuid
    qh = question_hash(question)
    with connect() as c, c:
        existing = c.execute(
            "SELECT id, times_used FROM answers WHERE question_hash = ?", (qh,)
        ).fetchone()
        if existing:
            c.execute(
                "UPDATE answers SET answer_text = ?, question_text = ? WHERE id = ?",
                (answer, question, existing["id"]),
            )
            return {"ok": True, "answer_id": existing["id"], "updated": True}
        new_id = uuid.uuid4().hex
        c.execute(
            "INSERT INTO answers (id, question_hash, question_text, answer_text) VALUES (?, ?, ?, ?)",
            (new_id, qh, question, answer),
        )
        return {"ok": True, "answer_id": new_id, "updated": False}


def lookup_answer(question: str) -> Optional[str]:
    qh = question_hash(question)
    with connect() as c, c:
        row = c.execute(
            "SELECT id, answer_text FROM answers WHERE question_hash = ?", (qh,)
        ).fetchone()
        if not row:
            return None
        # Bump usage counters in the same txn — read-write atomicity.
        c.execute(
            "UPDATE answers SET times_used = times_used + 1, last_used_at = datetime('now') WHERE id = ?",
            (row["id"],),
        )
        return row["answer_text"]


def list_answers(limit: int = 100) -> list[dict[str, Any]]:
    with connect() as c:
        rows = c.execute(
            "SELECT id, question_text, answer_text, times_used, last_used_at, created_at "
            "FROM answers ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def delete_answer(answer_id: str) -> bool:
    with connect() as c, c:
        cur = c.execute("DELETE FROM answers WHERE id = ?", (answer_id,))
        return cur.rowcount > 0


# ─── Jobs + Applications ────────────────────────────────────────
def upsert_job(
    source: str,
    external_id: str,
    company_name: str,
    title: str,
    apply_url: str,
    location: Optional[str] = None,
    description: Optional[str] = None,
) -> str:
    """Returns the local job_id (uuid4 hex)."""
    import uuid
    with connect() as c, c:
        existing = c.execute(
            "SELECT id FROM jobs WHERE source = ? AND external_id = ?",
            (source, external_id),
        ).fetchone()
        if existing:
            return existing["id"]
        new_id = uuid.uuid4().hex
        c.execute(
            "INSERT INTO jobs (id, source, external_id, company_name, title, location, apply_url, description) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id, source, external_id, company_name, title, location, apply_url, description),
        )
        return new_id


def find_job_by_apply_url(apply_url: str) -> Optional[dict[str, Any]]:
    with connect() as c:
        row = c.execute(
            "SELECT id, source, external_id, company_name, title, location, apply_url, description "
            "FROM jobs WHERE apply_url = ? LIMIT 1",
            (apply_url,),
        ).fetchone()
        return dict(row) if row else None


def queue_application(job_id: str) -> dict[str, Any]:
    """Insert (or return existing) application row in `queued` status."""
    import uuid
    with connect() as c, c:
        existing = c.execute(
            "SELECT id, status FROM applications WHERE job_id = ?", (job_id,)
        ).fetchone()
        if existing:
            return {"ok": True, "application_id": existing["id"], "status": existing["status"], "already_existed": True}
        new_id = uuid.uuid4().hex
        c.execute(
            "INSERT INTO applications (id, job_id, status) VALUES (?, ?, 'queued')",
            (new_id, job_id),
        )
        return {"ok": True, "application_id": new_id, "status": "queued", "already_existed": False}


def update_application(
    application_id: str,
    *,
    status: Optional[str] = None,
    submission_log: Optional[dict[str, Any]] = None,
    error_message: Optional[str] = None,
    started_at: Optional[str] = None,
    completed_at: Optional[str] = None,
) -> bool:
    fields = []
    values: list[Any] = []
    if status is not None:
        fields.append("status = ?"); values.append(status)
    if submission_log is not None:
        fields.append("submission_log = ?"); values.append(json.dumps(submission_log, default=str))
    if error_message is not None:
        fields.append("error_message = ?"); values.append(error_message)
    if started_at is not None:
        fields.append("started_at = ?"); values.append(started_at)
    if completed_at is not None:
        fields.append("completed_at = ?"); values.append(completed_at)
    if not fields:
        return False
    values.append(application_id)
    with connect() as c, c:
        cur = c.execute(f"UPDATE applications SET {', '.join(fields)} WHERE id = ?", values)
        return cur.rowcount > 0


def list_applications(status: Optional[str] = None, limit: int = 100) -> list[dict[str, Any]]:
    sql = (
        "SELECT a.id, a.status, a.submission_log, a.error_message, a.queued_at, "
        "       a.started_at, a.completed_at, "
        "       j.company_name, j.title, j.apply_url, j.location "
        "FROM applications a JOIN jobs j ON j.id = a.job_id "
    )
    values: list[Any] = []
    if status:
        sql += "WHERE a.status = ? "
        values.append(status)
    sql += "ORDER BY a.queued_at DESC LIMIT ?"
    values.append(limit)
    with connect() as c:
        rows = c.execute(sql, values).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            if d.get("submission_log"):
                try:
                    d["submission_log"] = json.loads(d["submission_log"])
                except json.JSONDecodeError:
                    pass
            out.append(d)
        return out


def get_status_summary() -> dict[str, int]:
    with connect() as c:
        rows = c.execute(
            "SELECT status, COUNT(*) AS n FROM applications GROUP BY status"
        ).fetchall()
        out = {r["status"]: r["n"] for r in rows}
        out["total_jobs_cached"] = c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        out["total_answers_saved"] = c.execute("SELECT COUNT(*) FROM answers").fetchone()[0]
        return out
