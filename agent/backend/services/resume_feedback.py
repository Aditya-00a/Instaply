from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.db.database import get_connection, init_db
from backend.services.config import settings
from backend.services.jd_parser import parse_job_description
from backend.services.pdf_renderer import build_ats_resume_pdf
from backend.services.review_commands import get_resume_preference_overrides
from backend.services.tailor import tailor_resume

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


def _extract_generated_lists(tailored_resume: dict[str, Any]) -> dict[str, list[str]]:
    return {
        "experience": [str(item.get("company", "")).strip() for item in tailored_resume.get("experience", []) if str(item.get("company", "")).strip()],
        "projects": [str(item.get("name", "")).strip() for item in tailored_resume.get("projects", []) if str(item.get("name", "")).strip()],
        "publications": [str(item.get("title", "")).strip() for item in tailored_resume.get("publications", []) if str(item.get("title", "")).strip()],
        "leadership": [
            " | ".join(
                part for part in [str(item.get("role", "")).strip(), str(item.get("organization", "")).strip()] if part
            )
            for item in tailored_resume.get("leadership", [])
            if str(item.get("role", "")).strip() or str(item.get("organization", "")).strip()
        ],
    }


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


def _default_feedback_payload(decision: str, tailored_resume: dict[str, Any]) -> dict[str, list[str]]:
    generated = _extract_generated_lists(tailored_resume)
    if decision == "rejected":
        return {
            "kept_experience": [],
            "removed_experience": generated["experience"],
            "kept_projects": [],
            "removed_projects": generated["projects"],
            "kept_publications": [],
            "removed_publications": generated["publications"],
            "kept_leadership": [],
            "removed_leadership": generated["leadership"],
        }

    return {
        "kept_experience": generated["experience"],
        "removed_experience": [],
        "kept_projects": generated["projects"],
        "removed_projects": [],
        "kept_publications": generated["publications"],
        "removed_publications": [],
        "kept_leadership": generated["leadership"],
        "removed_leadership": [],
    }


def create_resume_generation(
    *,
    jd_text: str,
    role_bucket: str,
    company_context: dict[str, Any],
    company_background: str,
    tailored_resume: dict[str, Any],
    selection_summary: dict[str, Any],
    pdf_result: dict[str, Any],
) -> str:
    generation_id = str(uuid4())
    jd_hash = hashlib.sha256(jd_text.encode("utf-8")).hexdigest()
    with get_connection(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO resume_generations (
              id, role_bucket, company, role_title, company_background,
              jd_hash, jd_text, tailored_resume_json, selection_summary_json,
              pdf_path, docx_path
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
                _json_dumps(tailored_resume),
                _json_dumps(selection_summary),
                str(pdf_result.get("pdf_path", "")).strip(),
                str(pdf_result.get("docx_path", "")).strip(),
            ),
        )
        conn.commit()
    return generation_id


def get_learning_profile(role_bucket: str) -> dict[str, Any]:
    experience_boosts: defaultdict[str, int] = defaultdict(int)
    project_boosts: defaultdict[str, int] = defaultdict(int)
    publication_boosts: defaultdict[str, int] = defaultdict(int)
    leadership_boosts: defaultdict[str, int] = defaultdict(int)
    section_boosts: defaultdict[str, int] = defaultdict(int)
    feedback_counts: defaultdict[str, int] = defaultdict(int)

    with get_connection(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT
              f.decision,
              f.kept_experience_json,
              f.removed_experience_json,
              f.kept_projects_json,
              f.removed_projects_json,
              f.kept_publications_json,
              f.removed_publications_json,
              f.kept_leadership_json,
              f.removed_leadership_json
            FROM resume_feedback f
            JOIN resume_generations g ON g.id = f.generation_id
            WHERE g.role_bucket = ?
            """,
            (role_bucket,),
        ).fetchall()

    for row in rows:
        decision = str(row["decision"]).strip().lower()
        weight = DECISION_WEIGHTS.get(decision, 1)
        feedback_counts[decision] += 1

        def apply(items_json: str | None, bucket: defaultdict[str, int], direction: int, section_name: str) -> None:
            items = json.loads(items_json or "[]")
            if not isinstance(items, list):
                return
            cleaned = _coerce_list(items)
            for item in cleaned:
                bucket[item] += direction * weight
            if cleaned:
                section_boosts[section_name] += direction * weight

        apply(row["kept_experience_json"], experience_boosts, 1, "experience")
        apply(row["removed_experience_json"], experience_boosts, -1, "experience")
        apply(row["kept_projects_json"], project_boosts, 1, "projects")
        apply(row["removed_projects_json"], project_boosts, -1, "projects")
        apply(row["kept_publications_json"], publication_boosts, 1, "publications")
        apply(row["removed_publications_json"], publication_boosts, -1, "publications")
        apply(row["kept_leadership_json"], leadership_boosts, 1, "leadership")
        apply(row["removed_leadership_json"], leadership_boosts, -1, "leadership")

    return {
        "role_bucket": role_bucket,
        "experience_boosts": dict(experience_boosts),
        "project_boosts": dict(project_boosts),
        "publication_boosts": dict(publication_boosts),
        "leadership_boosts": dict(leadership_boosts),
        "section_boosts": dict(section_boosts),
        "feedback_counts": dict(feedback_counts),
    }


def _merge_resume_preference_overrides(learning_profile: dict[str, Any], role_bucket: str) -> dict[str, Any]:
    overrides = get_resume_preference_overrides(role_bucket)
    merged = dict(learning_profile)
    merged["experience_boosts"] = {
        **dict(learning_profile.get("experience_boosts", {})),
        **{
            key: int(learning_profile.get("experience_boosts", {}).get(key, 0)) + int(value)
            for key, value in overrides.get("experience_boosts", {}).items()
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
    merged["section_boosts"] = {
        **dict(learning_profile.get("section_boosts", {})),
        **{
            key: int(learning_profile.get("section_boosts", {}).get(key, 0)) + int(value)
            for key, value in overrides.get("section_boosts", {}).items()
        },
    }
    return merged


def generate_resume_with_learning(
    *,
    master_resume: dict[str, Any],
    jd_text: str,
    company_context: dict[str, Any] | None = None,
    company_background: str = "",
    output_filename: str | None = None,
    output_dir: str | None = None,
) -> dict[str, Any]:
    company_context = company_context or {}
    parsed = parse_job_description(jd_text, company_context)
    role_bucket = _normalize_role_bucket(parsed["role_type"])
    learning_profile = _merge_resume_preference_overrides(get_learning_profile(role_bucket), role_bucket)

    tailored_result = tailor_resume(
        master_resume,
        jd_text,
        company_context=company_context,
        company_background=company_background,
        learning_profile=learning_profile,
    )
    pdf_result = build_ats_resume_pdf(
        tailored_resume=tailored_result["tailored_resume"],
        output_filename=output_filename,
        output_dir=output_dir,
    )
    generation_id = create_resume_generation(
        jd_text=jd_text,
        role_bucket=tailored_result["role_bucket"],
        company_context=company_context,
        company_background=company_background,
        tailored_resume=tailored_result["tailored_resume"],
        selection_summary=tailored_result["selection_summary"],
        pdf_result=pdf_result,
    )

    return {
        **tailored_result,
        "generation_id": generation_id,
        "pdf_result": pdf_result,
        "learning_profile": learning_profile,
    }


def record_resume_feedback(
    *,
    generation_id: str,
    decision: str,
    notes: str = "",
    kept_experience: list[str] | None = None,
    removed_experience: list[str] | None = None,
    kept_projects: list[str] | None = None,
    removed_projects: list[str] | None = None,
    kept_publications: list[str] | None = None,
    removed_publications: list[str] | None = None,
    kept_leadership: list[str] | None = None,
    removed_leadership: list[str] | None = None,
) -> dict[str, Any]:
    with get_connection(DB_PATH) as conn:
        generation = conn.execute(
            "SELECT role_bucket, tailored_resume_json FROM resume_generations WHERE id = ?",
            (generation_id,),
        ).fetchone()
        if generation is None:
            raise ValueError(f"Unknown generation_id: {generation_id}")

        tailored_resume = json.loads(generation["tailored_resume_json"])
        defaults = _default_feedback_payload(decision, tailored_resume)
        payload = {
            "kept_experience": _coerce_list(kept_experience) or defaults["kept_experience"],
            "removed_experience": _coerce_list(removed_experience) or defaults["removed_experience"],
            "kept_projects": _coerce_list(kept_projects) or defaults["kept_projects"],
            "removed_projects": _coerce_list(removed_projects) or defaults["removed_projects"],
            "kept_publications": _coerce_list(kept_publications) or defaults["kept_publications"],
            "removed_publications": _coerce_list(removed_publications) or defaults["removed_publications"],
            "kept_leadership": _coerce_list(kept_leadership) or defaults["kept_leadership"],
            "removed_leadership": _coerce_list(removed_leadership) or defaults["removed_leadership"],
        }

        feedback_id = str(uuid4())
        conn.execute(
            """
            INSERT INTO resume_feedback (
              id, generation_id, decision, notes,
              kept_experience_json, removed_experience_json,
              kept_projects_json, removed_projects_json,
              kept_publications_json, removed_publications_json,
              kept_leadership_json, removed_leadership_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                feedback_id,
                generation_id,
                decision,
                notes,
                _json_dumps(payload["kept_experience"]),
                _json_dumps(payload["removed_experience"]),
                _json_dumps(payload["kept_projects"]),
                _json_dumps(payload["removed_projects"]),
                _json_dumps(payload["kept_publications"]),
                _json_dumps(payload["removed_publications"]),
                _json_dumps(payload["kept_leadership"]),
                _json_dumps(payload["removed_leadership"]),
            ),
        )
        conn.commit()

    learning_profile = get_learning_profile(str(generation["role_bucket"]).strip())
    return {
        "feedback_id": feedback_id,
        "generation_id": generation_id,
        "decision": decision,
        "applied_feedback": payload,
        "learning_profile": learning_profile,
    }
