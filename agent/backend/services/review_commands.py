from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.db.database import get_connection, init_db
from backend.services.config import settings
from backend.services.files import load_master_resume

DB_PATH = init_db(Path(settings.database_path))

ROLE_ALIASES = {
    "product_strategy": "ai_product",
    "product": "ai_product",
    "operator": "operator_startup",
    "startup": "operator_startup",
    "technical": "technical",
    "consulting": "consulting",
    "corporate": "corporate",
    "research": "research",
    "risk": "risk_analytics",
    "risk_analytics": "risk_analytics",
}

SECTION_ALIASES = {
    "experience": "experience",
    "experiences": "experience",
    "projects": "projects",
    "project": "projects",
    "publications": "publications",
    "publication": "publications",
    "research": "publications",
    "research papers": "publications",
    "skills": "skills",
    "leadership": "leadership",
    "business fit": "business_fit",
    "technical alignment": "technical_alignment",
    "execution": "execution",
    "closing": "closing",
}


def normalize_role_bucket(role_text: str) -> str:
    text = str(role_text or "").strip().lower().replace("-", "_").replace(" ", "_")
    return ROLE_ALIASES.get(text, text or "consulting")


def _split_items(text: str) -> list[str]:
    cleaned = re.sub(r"\s+(and|&)\s+", "+", text, flags=re.IGNORECASE)
    parts = [part.strip() for part in cleaned.split("+")]
    return [part for part in parts if part]


def _canonical_company_name(name: str) -> str:
    target = str(name or "").strip()
    if not target:
        return target
    master_resume = load_master_resume()
    companies = [
        str(exp.get("company", "")).strip()
        for exp in master_resume.get("experience", [])
        if str(exp.get("company", "")).strip()
    ]
    lowered = target.lower()
    for company in companies:
        company_lower = company.lower()
        if lowered == company_lower or lowered in company_lower or company_lower in lowered:
            return company
    return target


def _canonical_project_name(name: str) -> str:
    target = str(name or "").strip()
    if not target:
        return target
    alias_map = {
        "legacy_consulting": "Legacy consulting project (placeholder)",
        "women's world banking": "Legacy consulting project (placeholder)",
        "womens world banking": "Legacy consulting project (placeholder)",
    }
    lowered = target.lower()
    if lowered in alias_map:
        return alias_map[lowered]

    master_resume = load_master_resume()
    projects = [
        str(project.get("name", "")).strip()
        for project in master_resume.get("projects", [])
        if str(project.get("name", "")).strip()
    ]
    for project in projects:
        project_lower = project.lower()
        if lowered == project_lower or lowered in project_lower or project_lower in lowered:
            return project
    return target


def _resolve_preference_item(name: str) -> tuple[str, str]:
    project_name = _canonical_project_name(name)
    if project_name != str(name or "").strip():
        return "project_preference", project_name

    company_name = _canonical_company_name(name)
    return "company_preference", company_name


def _canonical_section_name(name: str) -> str:
    text = str(name or "").strip().lower()
    return SECTION_ALIASES.get(text, text.replace(" ", "_"))


def create_review_preference(
    *,
    applies_to: str,
    role_bucket: str,
    preference_type: str,
    item_name: str,
    value: str = "",
    weight: int = 2,
) -> str:
    preference_id = str(uuid4())
    with get_connection(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO review_preferences (
              id, applies_to, role_bucket, preference_type, item_name, value, weight, active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (preference_id, applies_to, role_bucket, preference_type, item_name, value, weight),
        )
        conn.commit()
    return preference_id


def _load_review_preferences(applies_to: str, role_bucket: str) -> list[dict[str, Any]]:
    buckets = [role_bucket, "*"]
    scopes = [applies_to, "both"]
    with get_connection(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT applies_to, role_bucket, preference_type, item_name, value, weight
            FROM review_preferences
            WHERE active = 1
              AND applies_to IN (?, ?)
              AND role_bucket IN (?, ?)
            ORDER BY created_at ASC
            """,
            (scopes[0], scopes[1], buckets[0], buckets[1]),
        ).fetchall()
    return [dict(row) for row in rows]


def get_resume_preference_overrides(role_bucket: str) -> dict[str, Any]:
    experience_boosts: dict[str, int] = {}
    project_boosts: dict[str, int] = {}
    section_boosts: dict[str, int] = {}
    rules: dict[str, Any] = {}
    for row in _load_review_preferences("resume", role_bucket):
        pref_type = str(row["preference_type"])
        item_name = str(row["item_name"])
        weight = int(row["weight"] or 0)
        if pref_type == "company_preference":
            experience_boosts[item_name] = experience_boosts.get(item_name, 0) + weight
        elif pref_type == "project_preference":
            project_boosts[item_name] = project_boosts.get(item_name, 0) + weight
        elif pref_type == "section_preference":
            section_boosts[item_name] = section_boosts.get(item_name, 0) + weight
        elif pref_type == "rule":
            rules[item_name] = str(row["value"] or "")
    return {
        "experience_boosts": experience_boosts,
        "project_boosts": project_boosts,
        "section_boosts": section_boosts,
        "rules": rules,
    }


def get_cover_letter_preference_overrides(role_bucket: str) -> dict[str, Any]:
    example_boosts: dict[str, int] = {}
    project_boosts: dict[str, int] = {}
    paragraph_emphasis_boosts: dict[str, int] = {}
    rules: dict[str, Any] = {}
    for row in _load_review_preferences("cover_letter", role_bucket):
        pref_type = str(row["preference_type"])
        item_name = str(row["item_name"])
        weight = int(row["weight"] or 0)
        if pref_type == "company_preference":
            example_boosts[item_name] = example_boosts.get(item_name, 0) + weight
        elif pref_type == "project_preference":
            project_boosts[item_name] = project_boosts.get(item_name, 0) + weight
        elif pref_type == "paragraph_preference":
            paragraph_emphasis_boosts[item_name] = paragraph_emphasis_boosts.get(item_name, 0) + weight
        elif pref_type == "rule":
            rules[item_name] = str(row["value"] or "")
    return {
        "example_boosts": example_boosts,
        "project_boosts": project_boosts,
        "paragraph_emphasis_boosts": paragraph_emphasis_boosts,
        "rules": rules,
    }


def apply_review_command(
    *,
    command: str,
    generation_id: str = "",
    role_bucket: str = "",
) -> dict[str, Any]:
    raw = str(command or "").strip()
    lowered = raw.lower().strip()
    normalize_role_bucket(role_bucket) if role_bucket else ""

    if re.fullmatch(r"approve\s+cover\s*letter", lowered):
        if not generation_id:
            raise ValueError("generation_id is required for 'approve cover letter'")
        from backend.services.cover_letter_feedback import record_cover_letter_feedback

        result = record_cover_letter_feedback(generation_id=generation_id, decision="approved")
        return {"command": raw, "action": "cover_letter_feedback_recorded", "result": result}

    if re.fullmatch(r"reject\s+cover\s*letter", lowered):
        if not generation_id:
            raise ValueError("generation_id is required for 'reject cover letter'")
        from backend.services.cover_letter_feedback import record_cover_letter_feedback

        result = record_cover_letter_feedback(generation_id=generation_id, decision="rejected")
        return {"command": raw, "action": "cover_letter_feedback_recorded", "result": result}

    if re.fullmatch(r"approve\s+resume", lowered):
        if not generation_id:
            raise ValueError("generation_id is required for 'approve resume'")
        from backend.services.resume_feedback import record_resume_feedback

        result = record_resume_feedback(generation_id=generation_id, decision="approved")
        return {"command": raw, "action": "resume_feedback_recorded", "result": result}

    if re.fullmatch(r"reject\s+resume", lowered):
        if not generation_id:
            raise ValueError("generation_id is required for 'reject resume'")
        from backend.services.resume_feedback import record_resume_feedback

        result = record_resume_feedback(generation_id=generation_id, decision="rejected")
        return {"command": raw, "action": "resume_feedback_recorded", "result": result}

    prefer_project_match = re.fullmatch(r"prefer\s+project\s+(.+?)\s+for\s+([a-zA-Z _-]+)", raw, flags=re.IGNORECASE)
    if prefer_project_match:
        item = _canonical_project_name(prefer_project_match.group(1))
        bucket = normalize_role_bucket(prefer_project_match.group(2))
        created = [
            create_review_preference(
                applies_to="both",
                role_bucket=bucket,
                preference_type="project_preference",
                item_name=item,
                weight=2,
            )
        ]
        return {
            "command": raw,
            "action": "project_preference_saved",
            "result": {"role_bucket": bucket, "project": item, "preference_ids": created},
        }

    prefer_example_match = re.fullmatch(r"prefer\s+example\s+(.+?)\s+for\s+([a-zA-Z _-]+)", raw, flags=re.IGNORECASE)
    if prefer_example_match:
        item = _canonical_company_name(prefer_example_match.group(1))
        bucket = normalize_role_bucket(prefer_example_match.group(2))
        created = [
            create_review_preference(
                applies_to="cover_letter",
                role_bucket=bucket,
                preference_type="company_preference",
                item_name=item,
                weight=2,
            )
        ]
        return {
            "command": raw,
            "action": "cover_letter_example_saved",
            "result": {"role_bucket": bucket, "example": item, "preference_ids": created},
        }

    prefer_match = re.fullmatch(r"prefer\s+(.+?)\s+for\s+([a-zA-Z _-]+)", raw, flags=re.IGNORECASE)
    if prefer_match:
        items = _split_items(prefer_match.group(1))
        bucket = normalize_role_bucket(prefer_match.group(2))
        resolved_items = [_resolve_preference_item(item) for item in items]
        created: list[str] = []
        payload_items: list[str] = []
        for pref_type, item in resolved_items:
            payload_items.append(item)
            created.append(
                create_review_preference(
                    applies_to="both",
                    role_bucket=bucket,
                    preference_type=pref_type,
                    item_name=item,
                    weight=2,
                )
            )
        return {
            "command": raw,
            "action": "role_preference_saved",
            "result": {
                "role_bucket": bucket,
                "preferred_items": payload_items,
                "preference_ids": created,
            },
        }

    avoid_match = re.fullmatch(r"avoid\s+(.+?)\s+for\s+([a-zA-Z _-]+)", raw, flags=re.IGNORECASE)
    if avoid_match:
        items = _split_items(avoid_match.group(1))
        bucket = normalize_role_bucket(avoid_match.group(2))
        resolved_items = [_resolve_preference_item(item) for item in items]
        created: list[str] = []
        payload_items: list[str] = []
        for pref_type, item in resolved_items:
            payload_items.append(item)
            created.append(
                create_review_preference(
                    applies_to="both",
                    role_bucket=bucket,
                    preference_type=pref_type,
                    item_name=item,
                    weight=-2,
                )
            )
        return {
            "command": raw,
            "action": "role_avoidance_saved",
            "result": {
                "role_bucket": bucket,
                "avoided_items": payload_items,
                "preference_ids": created,
            },
        }

    tone_match = re.fullmatch(r"([a-zA-Z]+)\s+tone\s+for\s+([a-zA-Z _-]+)", raw, flags=re.IGNORECASE)
    if tone_match:
        tone = str(tone_match.group(1)).strip().lower()
        bucket = normalize_role_bucket(tone_match.group(2))
        preference_id = create_review_preference(
            applies_to="cover_letter",
            role_bucket=bucket,
            preference_type="rule",
            item_name="tone",
            value=tone,
            weight=2,
        )
        return {
            "command": raw,
            "action": "cover_letter_tone_saved",
            "result": {
                "role_bucket": bucket,
                "tone": tone,
                "preference_ids": [preference_id],
            },
        }

    length_match = re.fullmatch(r"(shorter|longer)\s+cover\s*letter\s+for\s+([a-zA-Z _-]+)", raw, flags=re.IGNORECASE)
    if length_match:
        length_mode = "short" if length_match.group(1).strip().lower() == "shorter" else "long"
        bucket = normalize_role_bucket(length_match.group(2))
        preference_id = create_review_preference(
            applies_to="cover_letter",
            role_bucket=bucket,
            preference_type="rule",
            item_name="length",
            value=length_mode,
            weight=2,
        )
        return {
            "command": raw,
            "action": "cover_letter_length_saved",
            "result": {
                "role_bucket": bucket,
                "length": length_mode,
                "preference_ids": [preference_id],
            },
        }

    hide_match = re.fullmatch(r"hide\s+leadership\s+for\s+([a-zA-Z _-]+)", raw, flags=re.IGNORECASE)
    if hide_match:
        bucket = normalize_role_bucket(hide_match.group(1))
        preference_id = create_review_preference(
            applies_to="resume",
            role_bucket=bucket,
            preference_type="rule",
            item_name="hide_leadership",
            value="true",
            weight=2,
        )
        return {
            "command": raw,
            "action": "resume_rule_saved",
            "result": {
                "role_bucket": bucket,
                "rule": "hide_leadership",
                "value": "true",
                "preference_ids": [preference_id],
            },
        }

    show_match = re.fullmatch(r"show\s+leadership\s+for\s+([a-zA-Z _-]+)", raw, flags=re.IGNORECASE)
    if show_match:
        bucket = normalize_role_bucket(show_match.group(1))
        preference_id = create_review_preference(
            applies_to="resume",
            role_bucket=bucket,
            preference_type="rule",
            item_name="hide_leadership",
            value="false",
            weight=2,
        )
        return {
            "command": raw,
            "action": "resume_rule_saved",
            "result": {
                "role_bucket": bucket,
                "rule": "hide_leadership",
                "value": "false",
                "preference_ids": [preference_id],
            },
        }

    section_match = re.fullmatch(r"(prioritize|deprioritize)\s+(.+?)\s+for\s+([a-zA-Z _-]+)", raw, flags=re.IGNORECASE)
    if section_match:
        direction = 2 if section_match.group(1).strip().lower() == "prioritize" else -2
        section_name = _canonical_section_name(section_match.group(2))
        bucket = normalize_role_bucket(section_match.group(3))
        applies_to = "cover_letter" if section_name in {"business_fit", "technical_alignment", "execution", "closing"} else "resume"
        pref_type = "paragraph_preference" if applies_to == "cover_letter" else "section_preference"
        preference_id = create_review_preference(
            applies_to=applies_to,
            role_bucket=bucket,
            preference_type=pref_type,
            item_name=section_name,
            weight=direction,
        )
        return {
            "command": raw,
            "action": "priority_preference_saved",
            "result": {
                "role_bucket": bucket,
                "applies_to": applies_to,
                "target": section_name,
                "weight": direction,
                "preference_ids": [preference_id],
            },
        }

    if re.fullmatch(r"use\s+filler\s+for\s+university\s+roles\s+only", lowered):
        created = [
            create_review_preference(
                applies_to="both",
                role_bucket="*",
                preference_type="rule",
                item_name="filler_mode",
                value="university_only",
                weight=2,
            )
        ]
        return {
            "command": raw,
            "action": "global_rule_saved",
            "result": {
                "rule": "filler_mode",
                "value": "university_only",
                "preference_ids": created,
            },
        }

    raise ValueError(f"Unsupported review command: {raw}")
