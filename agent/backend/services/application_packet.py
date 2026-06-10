from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from backend.services.cover_letter_feedback import generate_cover_letter_with_learning
from backend.services.resume_feedback import generate_resume_with_learning


def _safe_stem(value: str) -> str:
    candidate = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip()).strip("._-")
    return candidate or "application_packet"


def _company_stem(company_context: dict[str, Any], explicit_basename: str | None = None) -> str:
    company = str(company_context.get("company", "")).strip()
    if company:
        return _safe_stem(company)
    if explicit_basename:
        return _safe_stem(explicit_basename)
    return "Company"


def _build_output_basename(company_context: dict[str, Any], explicit_basename: str | None) -> str:
    if explicit_basename:
        return _safe_stem(explicit_basename)

    company = str(company_context.get("company", "")).strip().lower().replace(" ", "_")
    role = str(company_context.get("role", "")).strip().lower().replace(" ", "_")
    combined = "_".join(part for part in [company, role, "packet"] if part)
    return _safe_stem(combined or "application_packet")


def _packet_output_dir(output_dir: str | None, company_context: dict[str, Any], explicit_basename: str | None) -> str | None:
    if not output_dir:
        return None
    packet_dir = Path(output_dir) / _build_output_basename(company_context, explicit_basename)
    packet_dir.mkdir(parents=True, exist_ok=True)
    return str(packet_dir)


def _resume_filename(company_context: dict[str, Any], explicit_basename: str | None = None) -> str:
    return _safe_stem(f"application_{_company_stem(company_context, explicit_basename)}_resume")


def _cover_letter_filename(company_context: dict[str, Any], explicit_basename: str | None = None) -> str:
    return _safe_stem(f"application_{_company_stem(company_context, explicit_basename)}_Coverletter")


def build_suggested_review_commands(
    *,
    role_bucket: str,
    resume_generation_id: str,
    cover_letter_generation_id: str,
    cover_letter_summary: dict[str, Any],
) -> list[dict[str, str]]:
    suggestions: list[dict[str, str]] = [
        {
            "command": "approve resume",
            "generation_id": resume_generation_id,
            "applies_to": "resume",
            "reason": "Save this resume version as a strong baseline if it looks right.",
        },
        {
            "command": "reject resume",
            "generation_id": resume_generation_id,
            "applies_to": "resume",
            "reason": "Record that this resume version missed the mark so future ones move away from it.",
        },
        {
            "command": "approve cover letter",
            "generation_id": cover_letter_generation_id,
            "applies_to": "cover_letter",
            "reason": "Keep the current voice, examples, and structure for similar roles.",
        },
        {
            "command": "reject cover letter",
            "generation_id": cover_letter_generation_id,
            "applies_to": "cover_letter",
            "reason": "Tell the system to avoid this cover-letter direction next time.",
        },
    ]

    if role_bucket == "consulting":
        suggestions.extend(
            [
                {
                    "command": "technical tone for consulting",
                    "generation_id": "",
                    "applies_to": "cover_letter",
                    "reason": "Lean harder into delivery, integrations, and technical credibility for consulting roles.",
                },
                # TODO(post-lift): regenerate these from the user's actual
                # project list at profile-load time. Was hardcoded with
                # the original author's specific consulting projects.
                {
                    "command": "prefer client-facing projects for consulting",
                    "generation_id": "",
                    "applies_to": "resume",
                    "reason": "Boost the strongest consulting and client-facing examples for similar jobs.",
                },
                {
                    "command": "shorter cover letter for consulting",
                    "generation_id": "",
                    "applies_to": "cover_letter",
                    "reason": "Trim consulting cover letters if you want a tighter delivery-oriented style.",
                },
            ]
        )
    elif role_bucket == "technical":
        suggestions.extend(
            [
                # TODO(post-lift): regenerate from profile.projects.
                {
                    "command": "prefer platform-building projects for technical",
                    "generation_id": "",
                    "applies_to": "resume_cover_letter",
                    "reason": "Boost platform-building and integration-heavy project evidence for technical roles.",
                },
                {
                    "command": "hide leadership for technical",
                    "generation_id": "",
                    "applies_to": "resume",
                    "reason": "Keep more space for technical depth and implementation details.",
                },
            ]
        )
    elif role_bucket == "research":
        suggestions.append(
            {
                "command": "prioritize publications for research",
                "generation_id": "",
                "applies_to": "resume",
                "reason": "Push research papers higher for similar research-heavy applications.",
            }
        )
    elif role_bucket == "operator":
        suggestions.extend(
            [
                {
                    "command": "direct tone for operator",
                    "generation_id": "",
                    "applies_to": "cover_letter",
                    "reason": "Use a more straightforward operating tone for startup and builder roles.",
                },
                {
                    "command": "show leadership for operator",
                    "generation_id": "",
                    "applies_to": "resume",
                    "reason": "Bring leadership back when operator roles benefit from ownership signals.",
                },
            ]
        )

    # TODO(post-lift): rewrite this whole catalog from profile.projects so
    # the suggestion text reflects the active user's portfolio (was
    # hardcoded with the original author's project names).

    return suggestions


def generate_application_packet(
    *,
    jd_text: str,
    profile: dict[str, Any],
    master_resume: dict[str, Any],
    company_context: dict[str, Any] | None = None,
    company_background: str = "",
    output_basename: str | None = None,
    output_dir: str | None = None,
    date_text: str = "",
    recipient_lines: list[str] | None = None,
) -> dict[str, Any]:
    company_context = company_context or {}
    packet_output_dir = _packet_output_dir(output_dir, company_context, output_basename)

    resume_result = generate_resume_with_learning(
        master_resume=master_resume,
        jd_text=jd_text,
        company_context=company_context,
        company_background=company_background,
        output_filename=_resume_filename(company_context, output_basename),
        output_dir=packet_output_dir,
    )

    cover_letter_result = generate_cover_letter_with_learning(
        jd_text=jd_text,
        profile=profile,
        master_resume=master_resume,
        company_context=company_context,
        company_background=company_background,
        output_filename=_cover_letter_filename(company_context, output_basename),
        output_dir=packet_output_dir,
        date_text=date_text,
        recipient_lines=recipient_lines,
    )

    role_bucket = str(resume_result.get("role_bucket") or cover_letter_result.get("role_bucket") or "").strip()
    suggested_review_commands = _suggest_review_commands(
        role_bucket=role_bucket,
        resume_generation_id=str(resume_result.get("generation_id", "")).strip(),
        cover_letter_generation_id=str(cover_letter_result.get("generation_id", "")).strip(),
        cover_letter_summary=dict(cover_letter_result.get("selection_summary", {})),
    )

    return {
        "role_bucket": role_bucket,
        "generation_ids": {
            "resume": resume_result["generation_id"],
            "cover_letter": cover_letter_result["generation_id"],
        },
        "tailored_resume": resume_result["tailored_resume"],
        "cover_letter": cover_letter_result["cover_letter"],
        "pdfs": {
            "resume": str(resume_result["pdf_result"].get("docx_path", "")).strip(),
            "cover_letter": str(cover_letter_result["document_result"].get("docx_path", "")).strip(),
        },
        "docx": {
            "resume": str(resume_result["pdf_result"].get("docx_path", "")).strip(),
            "cover_letter": str(cover_letter_result["document_result"].get("docx_path", "")).strip(),
        },
        "documents": {
            "resume": resume_result["pdf_result"],
            "cover_letter": cover_letter_result["document_result"],
        },
        "selection_summaries": {
            "resume": resume_result["selection_summary"],
            "cover_letter": cover_letter_result["selection_summary"],
        },
        "resume": {
            "generation_id": resume_result["generation_id"],
            "selected_summary": resume_result["selected_summary"],
            "keyword_hits": resume_result["keyword_hits"],
            "ats_notes": resume_result["ats_notes"],
            "guardrails": resume_result["guardrails"],
            "jd_parse": resume_result["jd_parse"],
            "tailoring_audit": resume_result.get("tailoring_audit", {}),
            "pdf_result": resume_result["pdf_result"],
        },
        "cover_letter_result": {
            "generation_id": cover_letter_result["generation_id"],
            "selection_summary": cover_letter_result["selection_summary"],
            "document_result": cover_letter_result["document_result"],
        },
        "suggested_review_commands": suggested_review_commands,
    }


def _suggest_review_commands(
    *,
    role_bucket: str,
    resume_generation_id: str,
    cover_letter_generation_id: str,
    cover_letter_summary: dict[str, Any],
) -> list[dict[str, str]]:
    return build_suggested_review_commands(
        role_bucket=role_bucket,
        resume_generation_id=resume_generation_id,
        cover_letter_generation_id=cover_letter_generation_id,
        cover_letter_summary=cover_letter_summary,
    )
