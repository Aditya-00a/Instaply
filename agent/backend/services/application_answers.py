from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from backend.db.database import get_connection


def normalize_prompt(value: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", " ", str(value or "").strip().lower()).strip()


def infer_portal(*, job_source: str = "", job_url: str = "") -> str:
    normalized_source = normalize_prompt(job_source)
    normalized_url = str(job_url or "").lower()
    if normalized_source:
        return normalized_source.replace(" ", "_")
    if "jobs.lever.co" in normalized_url or "lever" in normalized_url:
        return "lever"
    if "greenhouse" in normalized_url:
        return "greenhouse"
    if "myworkdayjobs" in normalized_url or "workday" in normalized_url:
        return "workday"
    return "generic"


def _scope_candidates(*, portal: str = "", company: str = "") -> list[str]:
    normalized_portal = normalize_prompt(portal).replace(" ", "_") or "generic"
    normalized_company = normalize_prompt(company).replace(" ", "_")
    scopes: list[str] = []
    if normalized_company:
        scopes.append(f"{normalized_portal}:{normalized_company}")
    scopes.append(normalized_portal)
    scopes.append("global")
    return scopes


def _row_to_dict(row: Any) -> dict[str, Any]:
    return dict(row) if row is not None else {}


def lookup_application_answer(
    prompt: str,
    *,
    portal: str = "",
    company: str = "",
    control_kind: str = "",
    db_path: Path | None = None,
) -> dict[str, Any] | None:
    prompt_key = normalize_prompt(prompt)
    if not prompt_key:
        return None
    with get_connection(db_path) as conn:
        for scope in _scope_candidates(portal=portal, company=company):
            row = conn.execute(
                """
                SELECT *
                FROM application_answers
                WHERE prompt_key = ?
                  AND scope = ?
                  AND active = 1
                  AND (? = '' OR control_kind = ? OR control_kind = '')
                ORDER BY
                  CASE answer_source
                    WHEN 'user' THEN 0
                    WHEN 'observed' THEN 1
                    WHEN 'rule' THEN 2
                    ELSE 3
                  END,
                  updated_at DESC,
                  created_at DESC
                LIMIT 1
                """,
                (prompt_key, scope, control_kind, control_kind),
            ).fetchone()
            if row:
                return _row_to_dict(row)
    return None


def save_application_answer(
    prompt: str,
    answer: str,
    *,
    portal: str = "",
    company: str = "",
    control_kind: str = "",
    answer_source: str = "rule",
    confidence: float = 0.7,
    active: bool = True,
    db_path: Path | None = None,
) -> dict[str, Any] | None:
    prompt_text = str(prompt or "").strip()
    answer_text = str(answer or "").strip()
    prompt_key = normalize_prompt(prompt_text)
    if not prompt_key or not answer_text:
        return None
    scope = _scope_candidates(portal=portal, company=company)[0]
    row_id = hashlib.sha256(f"{scope}|{control_kind}|{prompt_key}".encode("utf-8")).hexdigest()
    with get_connection(db_path) as conn:
        existing = conn.execute(
            "SELECT id FROM application_answers WHERE id = ?",
            (row_id,),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE application_answers
                SET prompt_text = ?,
                    answer_text = ?,
                    answer_source = ?,
                    confidence = ?,
                    active = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (prompt_text, answer_text, answer_source, confidence, 1 if active else 0, row_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO application_answers (
                  id, scope, prompt_key, prompt_text, control_kind, answer_text,
                  answer_source, confidence, active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row_id,
                    scope,
                    prompt_key,
                    prompt_text,
                    str(control_kind or "").strip(),
                    answer_text,
                    answer_source,
                    confidence,
                    1 if active else 0,
                ),
            )
        conn.commit()
        row = conn.execute("SELECT * FROM application_answers WHERE id = ?", (row_id,)).fetchone()
        return _row_to_dict(row)


def get_or_learn_application_answer(
    prompt: str,
    *,
    portal: str = "",
    company: str = "",
    control_kind: str = "",
    fallback_answer: str = "",
    fallback_source: str = "rule",
    fallback_confidence: float = 0.7,
    db_path: Path | None = None,
) -> str:
    existing = lookup_application_answer(
        prompt,
        portal=portal,
        company=company,
        control_kind=control_kind,
        db_path=db_path,
    )
    if existing:
        return str(existing.get("answer_text") or "").strip()
    fallback = str(fallback_answer or "").strip()
    if fallback:
        save_application_answer(
            prompt,
            fallback,
            portal=portal,
            company=company,
            control_kind=control_kind,
            answer_source=fallback_source,
            confidence=fallback_confidence,
            db_path=db_path,
        )
    return fallback
