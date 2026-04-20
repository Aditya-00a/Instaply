from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.db.database import get_connection, init_db
from backend.services.config import settings
from backend.services.cover_letter_renderer import build_cover_letter_document
from backend.services.jd_parser import parse_job_description
from backend.services.review_commands import get_cover_letter_preference_overrides
from backend.services.tailor import generate_cover_letter

DB_PATH = init_db(Path(settings.database_path))

DECISION_WEIGHTS = {
    "approved": 3,
    "edited": 2,
    "rejected": 2,
}


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _normalize_role_bucket(role_type: str) -> str:
    return "ai_product" if role_type == "product_strategy" else role_type


def _coerce_list(values: list[str] | None) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values or []:
        item = str(value).strip()
        key = item.lower()
        if item and key not in seen:
            seen.add(key)
            cleaned.append(item)
    return cleaned


def _default_feedback_payload(decision: str, selection_summary: dict[str, Any]) -> dict[str, Any]:
    included_examples = _coerce_list(selection_summary.get("included_examples", []))
    included_projects = _coerce_list(selection_summary.get("included_projects", []))
    emphasis = _coerce_list(selection_summary.get("paragraph_emphasis_order", []))
    if decision == "rejected":
        return {
            "tone": str(selection_summary.get("tone", "")).strip(),
            "kept_examples": [],
            "removed_examples": included_examples,
            "kept_projects": [],
            "removed_projects": included_projects,
            "kept_paragraph_emphasis": [],
            "removed_paragraph_emphasis": emphasis,
        }
    return {
        "tone": str(selection_summary.get("tone", "")).strip(),
        "kept_examples": included_examples,
        "removed_examples": [],
        "kept_projects": included_projects,
        "removed_projects": [],
        "kept_paragraph_emphasis": emphasis,
        "removed_paragraph_emphasis": [],
    }


def create_cover_letter_generation(
    *,
    jd_text: str,
    role_bucket: str,
    company_context: dict[str, Any],
    company_background: str,
    cover_letter: str,
    selection_summary: dict[str, Any],
    document_result: dict[str, Any],
) -> str:
    generation_id = str(uuid4())
    jd_hash = hashlib.sha256(jd_text.encode("utf-8")).hexdigest()
    with get_connection(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO cover_letter_generations (
              id, role_bucket, company, role_title, company_background,
              jd_hash, jd_text, cover_letter_text, selection_summary_json,
              docx_path, pdf_path
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                generation_id,
                role_bucket,
                str(company_context.get("company", "")).strip(),
                str(company_context.get("role", "")).strip(),
                company_background,
                jd_hash,
                jd_text,
                cover_letter,
                _json_dumps(selection_summary),
                str(document_result.get("docx_path", "")).strip(),
                str(document_result.get("pdf_path", "")).strip(),
            ),
        )
        conn.commit()
    return generation_id


def get_cover_letter_learning_profile(role_bucket: str) -> dict[str, Any]:
    tone_preferences: defaultdict[str, int] = defaultdict(int)
    example_boosts: defaultdict[str, int] = defaultdict(int)
    project_boosts: defaultdict[str, int] = defaultdict(int)
    paragraph_emphasis_boosts: defaultdict[str, int] = defaultdict(int)
    feedback_counts: defaultdict[str, int] = defaultdict(int)

    with get_connection(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT
              f.decision,
              f.tone,
              f.kept_examples_json,
              f.removed_examples_json,
              f.kept_projects_json,
              f.removed_projects_json,
              f.kept_paragraph_emphasis_json,
              f.removed_paragraph_emphasis_json
            FROM cover_letter_feedback f
            JOIN cover_letter_generations g ON g.id = f.generation_id
            WHERE g.role_bucket = ?
            """,
            (role_bucket,),
        ).fetchall()

    for row in rows:
        decision = str(row["decision"]).strip().lower()
        weight = DECISION_WEIGHTS.get(decision, 1)
        feedback_counts[decision] += 1

        tone = str(row["tone"] or "").strip()
        if tone:
            tone_preferences[tone] += weight if decision in {"approved", "edited"} else -weight

        def apply(items_json: str | None, bucket: defaultdict[str, int], direction: int) -> None:
            items = json.loads(items_json or "[]")
            if not isinstance(items, list):
                return
            for item in _coerce_list(items):
                bucket[item] += direction * weight

        apply(row["kept_examples_json"], example_boosts, 1)
        apply(row["removed_examples_json"], example_boosts, -1)
        apply(row["kept_projects_json"], project_boosts, 1)
        apply(row["removed_projects_json"], project_boosts, -1)
        apply(row["kept_paragraph_emphasis_json"], paragraph_emphasis_boosts, 1)
        apply(row["removed_paragraph_emphasis_json"], paragraph_emphasis_boosts, -1)

    return {
        "role_bucket": role_bucket,
        "tone_preferences": dict(tone_preferences),
        "example_boosts": dict(example_boosts),
        "project_boosts": dict(project_boosts),
        "paragraph_emphasis_boosts": dict(paragraph_emphasis_boosts),
        "feedback_counts": dict(feedback_counts),
    }


def _merge_cover_letter_preference_overrides(learning_profile: dict[str, Any], role_bucket: str) -> dict[str, Any]:
    overrides = get_cover_letter_preference_overrides(role_bucket)
    merged = dict(learning_profile)
    merged["example_boosts"] = {
        **dict(learning_profile.get("example_boosts", {})),
        **{
            key: int(learning_profile.get("example_boosts", {}).get(key, 0)) + int(value)
            for key, value in overrides.get("example_boosts", {}).items()
        },
    }
    merged["project_boosts"] = {
        **dict(learning_profile.get("project_boosts", {})),
        **{
            key: int(learning_profile.get("project_boosts", {}).get(key, 0)) + int(value)
            for key, value in overrides.get("project_boosts", {}).items()
        },
    }
    merged["rules"] = {
        **dict(learning_profile.get("rules", {})),
        **dict(overrides.get("rules", {})),
    }
    merged["paragraph_emphasis_boosts"] = {
        **dict(learning_profile.get("paragraph_emphasis_boosts", {})),
        **{
            key: int(learning_profile.get("paragraph_emphasis_boosts", {}).get(key, 0)) + int(value)
            for key, value in overrides.get("paragraph_emphasis_boosts", {}).items()
        },
    }
    return merged


def generate_cover_letter_with_learning(
    *,
    jd_text: str,
    profile: dict[str, Any],
    master_resume: dict[str, Any],
    company_context: dict[str, Any] | None = None,
    company_background: str = "",
    output_filename: str | None = None,
    output_dir: str | None = None,
    date_text: str = "",
    recipient_lines: list[str] | None = None,
) -> dict[str, Any]:
    company_context = company_context or {}
    parsed = parse_job_description(jd_text, company_context)
    role_bucket = _normalize_role_bucket(parsed["role_type"])
    learning_profile = _merge_cover_letter_preference_overrides(get_cover_letter_learning_profile(role_bucket), role_bucket)
    generator_context = {**company_context, "learning_profile": learning_profile}

    generated = generate_cover_letter(
        jd_text=jd_text,
        profile=profile,
        company_context=generator_context,
        master_resume=master_resume,
        company_background=company_background,
    )
    document_result = build_cover_letter_document(
        cover_letter=generated["cover_letter"],
        contact=master_resume.get("contact", {}),
        company_context=company_context,
        date_text=date_text,
        recipient_lines=recipient_lines,
        signature_name=str(master_resume.get("name", "")).strip() or "",
        output_filename=output_filename,
        output_dir=output_dir,
    )
    generation_id = create_cover_letter_generation(
        jd_text=jd_text,
        role_bucket=generated["role_bucket"],
        company_context=company_context,
        company_background=company_background,
        cover_letter=generated["cover_letter"],
        selection_summary=generated["selection_summary"],
        document_result=document_result,
    )
    return {
        **generated,
        "generation_id": generation_id,
        "document_result": document_result,
        "learning_profile": learning_profile,
    }


def record_cover_letter_feedback(
    *,
    generation_id: str,
    decision: str,
    tone: str = "",
    notes: str = "",
    kept_examples: list[str] | None = None,
    removed_examples: list[str] | None = None,
    kept_projects: list[str] | None = None,
    removed_projects: list[str] | None = None,
    kept_paragraph_emphasis: list[str] | None = None,
    removed_paragraph_emphasis: list[str] | None = None,
) -> dict[str, Any]:
    with get_connection(DB_PATH) as conn:
        generation = conn.execute(
            "SELECT role_bucket, selection_summary_json FROM cover_letter_generations WHERE id = ?",
            (generation_id,),
        ).fetchone()
        if generation is None:
            raise ValueError(f"Unknown generation_id: {generation_id}")

        selection_summary = json.loads(generation["selection_summary_json"] or "{}")
        defaults = _default_feedback_payload(decision, selection_summary)
        payload = {
            "tone": str(tone).strip() or defaults["tone"],
            "kept_examples": _coerce_list(kept_examples) or defaults["kept_examples"],
            "removed_examples": _coerce_list(removed_examples) or defaults["removed_examples"],
            "kept_projects": _coerce_list(kept_projects) or defaults["kept_projects"],
            "removed_projects": _coerce_list(removed_projects) or defaults["removed_projects"],
            "kept_paragraph_emphasis": _coerce_list(kept_paragraph_emphasis) or defaults["kept_paragraph_emphasis"],
            "removed_paragraph_emphasis": _coerce_list(removed_paragraph_emphasis) or defaults["removed_paragraph_emphasis"],
        }

        feedback_id = str(uuid4())
        conn.execute(
            """
            INSERT INTO cover_letter_feedback (
              id, generation_id, decision, tone, notes,
              kept_examples_json, removed_examples_json,
              kept_projects_json, removed_projects_json,
              kept_paragraph_emphasis_json, removed_paragraph_emphasis_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                feedback_id,
                generation_id,
                decision,
                payload["tone"],
                notes,
                _json_dumps(payload["kept_examples"]),
                _json_dumps(payload["removed_examples"]),
                _json_dumps(payload["kept_projects"]),
                _json_dumps(payload["removed_projects"]),
                _json_dumps(payload["kept_paragraph_emphasis"]),
                _json_dumps(payload["removed_paragraph_emphasis"]),
            ),
        )
        conn.commit()

    learning_profile = get_cover_letter_learning_profile(str(generation["role_bucket"]).strip())
    return {
        "feedback_id": feedback_id,
        "generation_id": generation_id,
        "decision": decision,
        "applied_feedback": payload,
        "learning_profile": learning_profile,
    }
