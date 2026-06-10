from __future__ import annotations

import re
from typing import Any

from backend.services.matcher import extract_keywords
from backend.services.resume_guardrails import canonicalize_master_resume


MIN_TAILORING_SCORE = 75
MIN_KEYWORD_COVERAGE = 0.40

GENERIC_PHRASES = (
    "results-driven",
    "proven track record",
    "passionate about",
    "cross-functional collaboration",
    "leveraged",
    "utilized",
    "synergies",
    "dynamic environment",
)

ROLE_SIGNAL_TERMS = {
    "ai",
    "artificial intelligence",
    "machine learning",
    "llm",
    "generative ai",
    "analytics",
    "data",
    "risk",
    "governance",
    "compliance",
    "fraud",
    "model",
    "business",
    "operations",
    "strategy",
    "product",
    "sql",
    "python",
}


class ResumeTailoringError(ValueError):
    def __init__(self, audit: dict[str, Any]):
        self.audit = audit
        blockers = "; ".join(audit.get("blockers", [])) or "resume tailoring audit failed"
        super().__init__(blockers)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z][a-z0-9+#.-]{1,}", _normalize(value))
        if len(token) > 2
    }


def _resume_text(tailored_resume: dict[str, Any]) -> str:
    parts: list[str] = [
        str(tailored_resume.get("selected_summary", "")),
        str(tailored_resume.get("role_bucket", "")),
    ]
    for exp in tailored_resume.get("experience", []):
        parts.extend([str(exp.get("company", "")), str(exp.get("title", ""))])
        for bullet in exp.get("bullets", []):
            parts.append(str(bullet.get("text", "")) if isinstance(bullet, dict) else str(bullet))
    for project in tailored_resume.get("projects", []):
        parts.extend([
            str(project.get("name", "")),
            str(project.get("display_summary", project.get("summary", ""))),
        ])
    for publication in tailored_resume.get("publications", []):
        parts.extend([
            str(publication.get("title", "")),
            str(publication.get("display_summary", publication.get("summary", ""))),
        ])
    for group in tailored_resume.get("skills_display", []):
        parts.append(str(group.get("label", "")))
        parts.extend(str(item) for item in group.get("items", []))
    skills = tailored_resume.get("skills", {})
    if isinstance(skills, dict):
        for category, items in skills.items():
            parts.append(str(category))
            parts.extend(str(item) for item in items)
    return " ".join(part for part in parts if part)


def _master_sets(master_resume: dict[str, Any]) -> dict[str, set[str]]:
    canonical = canonicalize_master_resume(master_resume)
    return {
        "companies": {
            _normalize(exp.get("company", ""))
            for exp in canonical.get("experience", [])
            if _normalize(exp.get("company", ""))
        },
        "projects": {
            _normalize(project.get("name", ""))
            for project in canonical.get("projects", [])
            if _normalize(project.get("name", ""))
        },
        "publications": {
            _normalize(publication.get("title", ""))
            for publication in canonical.get("publications", [])
            if _normalize(publication.get("title", ""))
        },
    }


def _fact_lock_violations(master_resume: dict[str, Any], tailored_resume: dict[str, Any]) -> list[str]:
    allowed = _master_sets(master_resume)
    violations: list[str] = []
    for exp in tailored_resume.get("experience", []):
        company = _normalize(exp.get("company", ""))
        if company and company not in allowed["companies"]:
            violations.append(f"unverified company: {exp.get('company', '')}")
    for project in tailored_resume.get("projects", []):
        name = _normalize(project.get("name", ""))
        if name and name not in allowed["projects"]:
            violations.append(f"unverified project: {project.get('name', '')}")
    for publication in tailored_resume.get("publications", []):
        title = _normalize(publication.get("title", ""))
        if title and title not in allowed["publications"]:
            violations.append(f"unverified publication: {publication.get('title', '')}")
    return violations


def audit_tailored_resume(
    *,
    jd_text: str,
    tailored_resume: dict[str, Any],
    master_resume: dict[str, Any],
    company_context: dict[str, Any] | None = None,
    minimum_score: int = MIN_TAILORING_SCORE,
) -> dict[str, Any]:
    """Score whether the resume is tailored enough to enter application prep."""
    company_context = company_context or {}
    jd_keywords = extract_keywords(
        " ".join(
            part
            for part in [
                jd_text,
                str(company_context.get("company", "")),
                str(company_context.get("role", "")),
            ]
            if part
        ),
        limit=18,
    )
    resume_text = _resume_text(tailored_resume)
    resume_lower = _normalize(resume_text)
    summary_lower = _normalize(tailored_resume.get("selected_summary", ""))

    matched_keywords = [keyword for keyword in jd_keywords if _normalize(keyword) in resume_lower]
    keyword_coverage = len(matched_keywords) / max(len(jd_keywords), 1)

    jd_role_signals = sorted(term for term in ROLE_SIGNAL_TERMS if term in _normalize(jd_text))
    matched_role_signals = sorted(term for term in jd_role_signals if term in resume_lower)
    role_signal_coverage = len(matched_role_signals) / max(len(jd_role_signals), 1)

    jd_tokens = _tokens(jd_text)
    resume_tokens = _tokens(resume_text)
    token_overlap = len(jd_tokens & resume_tokens) / max(len(jd_tokens), 1)

    included_experience_count = len(tailored_resume.get("experience", []))
    included_project_count = len(tailored_resume.get("projects", []))
    summary_keyword_hits = [
        keyword for keyword in jd_keywords[:8] if _normalize(keyword) and _normalize(keyword) in summary_lower
    ]
    generic_phrase_hits = [phrase for phrase in GENERIC_PHRASES if phrase in resume_lower]
    fact_violations = _fact_lock_violations(master_resume, tailored_resume)

    score = 0
    score += min(35, round(keyword_coverage * 35))
    score += min(20, round(role_signal_coverage * 20))
    score += min(15, round(token_overlap * 60))
    score += 10 if summary_keyword_hits else 0
    score += 10 if included_experience_count >= 3 else max(0, included_experience_count * 3)
    score += 5 if included_project_count >= 1 else 0
    score += 5 if not generic_phrase_hits else max(0, 5 - len(generic_phrase_hits) * 2)

    blockers: list[str] = []
    warnings: list[str] = []

    if keyword_coverage < MIN_KEYWORD_COVERAGE:
        blockers.append(
            f"JD keyword coverage too low: {len(matched_keywords)}/{len(jd_keywords)}"
        )
    if jd_role_signals and role_signal_coverage < 0.50:
        blockers.append(
            f"role signal coverage too low: {len(matched_role_signals)}/{len(jd_role_signals)}"
        )
    if not summary_keyword_hits:
        blockers.append("summary does not echo the role/JD language")
    if included_experience_count < 2:
        blockers.append("not enough relevant experience selected")
    if fact_violations:
        blockers.extend(fact_violations)
    if score < minimum_score:
        blockers.append(f"tailoring score {score} below required {minimum_score}")
    if generic_phrase_hits:
        warnings.append(f"generic phrases present: {', '.join(generic_phrase_hits)}")

    return {
        "passed": not blockers,
        "score": score,
        "minimum_score": minimum_score,
        "keyword_coverage": round(keyword_coverage, 3),
        "matched_keywords": matched_keywords,
        "missing_keywords": [keyword for keyword in jd_keywords if keyword not in matched_keywords],
        "role_signal_coverage": round(role_signal_coverage, 3),
        "matched_role_signals": matched_role_signals,
        "missing_role_signals": [term for term in jd_role_signals if term not in matched_role_signals],
        "token_overlap": round(token_overlap, 3),
        "summary_keyword_hits": summary_keyword_hits,
        "included_experience_count": included_experience_count,
        "included_project_count": included_project_count,
        "fact_violations": fact_violations,
        "warnings": warnings,
        "blockers": blockers,
    }


def require_strong_tailoring(**kwargs: Any) -> dict[str, Any]:
    audit = audit_tailored_resume(**kwargs)
    if not audit["passed"]:
        raise ResumeTailoringError(audit)
    return audit

