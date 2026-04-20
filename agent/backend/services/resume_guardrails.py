from __future__ import annotations

from copy import deepcopy
from typing import Any


MAX_EXPERIENCE_ITEMS = 5
MAX_PROJECTS = 2
MAX_PUBLICATIONS = 2
MAX_BULLETS_PER_ROLE = 3
MAX_LEADERSHIP_ITEMS = 2
MAX_SKILL_ITEMS_PER_CATEGORY = 7
MAX_SUMMARY_CHARS = 260


def _normalize_text(value: str) -> str:
    return " ".join((value or "").strip().split())


def _coerce_bullets(raw_bullets: list[Any]) -> list[dict[str, Any]]:
    coerced: list[dict[str, Any]] = []
    for bullet in raw_bullets or []:
        if isinstance(bullet, dict):
            coerced.append(
                {
                    "text": _normalize_text(str(bullet.get("text", ""))),
                    "tags": [str(tag) for tag in bullet.get("tags", [])],
                }
            )
        else:
            coerced.append({"text": _normalize_text(str(bullet)), "tags": []})
    return [bullet for bullet in coerced if bullet["text"]]


def canonicalize_master_resume(master_resume: dict[str, Any]) -> dict[str, Any]:
    data = deepcopy(master_resume)

    if isinstance(data.get("education"), dict):
        data["education"] = [data["education"]]

    normalized_experience = []
    for exp in data.get("experience", [])[:]:
        entry: dict[str, Any] = {
            "company": _normalize_text(str(exp.get("company", ""))),
            "location": _normalize_text(str(exp.get("location", ""))),
            "title": _normalize_text(str(exp.get("title", ""))),
            "dates": _normalize_text(str(exp.get("dates", ""))),
            "bullets": _coerce_bullets(exp.get("bullets", [])),
        }
        # Preserve flexible-title metadata so the tailor can adapt the role name.
        if exp.get("flexible_title"):
            entry["flexible_title"] = True
            entry["title_variants"] = exp.get("title_variants", {})
        normalized_experience.append(entry)
    data["experience"] = normalized_experience

    normalized_projects = []
    for project in data.get("projects", []):
        summary = project.get("summary", project.get("description", ""))
        normalized_projects.append(
            {
                "name": _normalize_text(str(project.get("name", ""))),
                "summary": _normalize_text(str(summary)),
                "tags": [str(tag) for tag in project.get("tags", [])],
            }
        )
    data["projects"] = normalized_projects

    normalized_publications = []
    for publication in data.get("publications", []):
        normalized_publications.append(
            {
                "title": _normalize_text(str(publication.get("title", ""))),
                "venue": _normalize_text(str(publication.get("venue", ""))),
                "status": _normalize_text(str(publication.get("status", ""))),
                "summary": _normalize_text(str(publication.get("summary", ""))),
                "tags": [str(tag) for tag in publication.get("tags", [])],
            }
        )
    data["publications"] = normalized_publications

    normalized_leadership = []
    for item in data.get("leadership", []):
        normalized_leadership.append(
            {
                "role": _normalize_text(str(item.get("role", ""))),
                "organization": _normalize_text(str(item.get("organization", ""))),
                "description": _normalize_text(str(item.get("description", ""))),
                "location": _normalize_text(str(item.get("location", ""))),
                "dates": _normalize_text(str(item.get("dates", ""))),
            }
        )
    data["leadership"] = normalized_leadership

    skills = data.get("skills", {})
    if isinstance(skills, dict):
        normalized_skills: dict[str, list[str]] = {}
        for category, items in skills.items():
            if isinstance(items, str):
                normalized_skills[str(category)] = [
                    _normalize_text(part) for part in items.split(",") if _normalize_text(part)
                ]
            else:
                normalized_skills[str(category)] = [
                    _normalize_text(str(item)) for item in items if _normalize_text(str(item))
                ]
        data["skills"] = normalized_skills
    else:
        data["skills"] = {"Core Skills": [_normalize_text(str(item)) for item in skills]}

    return data


def build_fact_lock(master_resume: dict[str, Any]) -> dict[str, Any]:
    canonical = canonicalize_master_resume(master_resume)
    return {
        "name": canonical.get("name", ""),
        "experience": [
            {
                "company": exp["company"],
                "title": exp["title"],
                "dates": exp["dates"],
                "location": exp["location"],
            }
            for exp in canonical.get("experience", [])
        ],
        "projects": [project["name"] for project in canonical.get("projects", [])],
        "publications": [publication["title"] for publication in canonical.get("publications", [])],
        "education": [
            {
                "school": _normalize_text(str(edu.get("school", ""))),
                "program": _normalize_text(str(edu.get("program", edu.get("degree", "")))),
                "graduation": _normalize_text(str(edu.get("graduation", ""))),
            }
            for edu in canonical.get("education", [])
        ],
    }


def apply_one_page_limits(tailored_resume: dict[str, Any]) -> dict[str, Any]:
    constrained = deepcopy(tailored_resume)
    constrained["experience"] = constrained.get("experience", [])[:MAX_EXPERIENCE_ITEMS]
    for exp in constrained.get("experience", []):
        exp["bullets"] = exp.get("bullets", [])[:MAX_BULLETS_PER_ROLE]

    constrained["projects"] = constrained.get("projects", [])[:MAX_PROJECTS]
    constrained["publications"] = constrained.get("publications", [])[:MAX_PUBLICATIONS]
    constrained["leadership"] = constrained.get("leadership", [])[:MAX_LEADERSHIP_ITEMS]

    skills = constrained.get("skills", {})
    if isinstance(skills, dict):
        constrained["skills"] = {
            category: items[:MAX_SKILL_ITEMS_PER_CATEGORY] for category, items in skills.items()
        }

    summary = constrained.get("selected_summary", "")
    if len(summary) > MAX_SUMMARY_CHARS:
        constrained["selected_summary"] = summary[: MAX_SUMMARY_CHARS - 3].rstrip() + "..."

    return constrained


def make_ats_notes() -> list[str]:
    return [
        "Single-column ATS-friendly structure",
        "No fabricated companies, titles, or dates",
        "Summary, project descriptions, and skills can be tailored from existing verified experience only",
        "Experience bullets may be tightened for relevance and brevity, but cannot introduce new claims",
        "Projects and skills are prioritized for keyword relevance only",
        "Output constrained for one-page resume rendering",
    ]


def build_guardrail_report(master_resume: dict[str, Any], tailored_resume: dict[str, Any]) -> dict[str, Any]:
    return {
        "fact_lock": build_fact_lock(master_resume),
        "rules": {
            "can_reorder_bullets": True,
            "can_drop_lower-priority_content": True,
            "can_reword_summary_projects_skills": True,
            "can_reword_experience_bullets_with_fact_lock": True,
            "can_create_new_jobs": False,
            "can_change_titles": False,
            "can_change_companies": False,
            "can_change_dates": False,
            "can_add_unverified_metrics": False,
            "target_one_page": True,
            "ats_friendly": True,
        },
        "output_counts": {
            "experience_items": len(tailored_resume.get("experience", [])),
            "project_items": len(tailored_resume.get("projects", [])),
            "publication_items": len(tailored_resume.get("publications", [])),
            "leadership_items": len(tailored_resume.get("leadership", [])),
        },
    }
