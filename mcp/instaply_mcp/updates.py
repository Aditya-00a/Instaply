"""Chat-style update routing for Instaply MCP.

This tool is intentionally simple: it lets the host assistant pass a
natural-language "update this" message and have Instaply persist the
relevant local state without forcing the model to hand-craft structured
tool arguments every time.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from . import db


EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE_RE = re.compile(
    r"(?:(?:\+?\d{1,3}[\s\-().]*)?(?:\(?\d{3}\)?[\s\-().]*)\d{3}[\s\-().]*\d{4})"
)
URL_RE = re.compile(r"(https?://[^\s]+|(?:www\.)?[a-z0-9.-]+\.[a-z]{2,}(?:/[^\s]*)?)", re.I)
APP_ID_RE = re.compile(r"\b[a-f0-9]{8,32}\b", re.I)


def _clean_url(raw: str) -> str:
    s = raw.strip().rstrip(").,;")
    if s.lower().startswith(("http://", "https://")):
        return s
    return "https://" + s


def _extract_named_value(message: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        m = re.search(pattern, message, re.I)
        if m:
            return m.group(1).strip(" \t\r\n.,;:-")
    return None


def _parse_location(value: str) -> dict[str, str]:
    value = re.split(r"\s+(?:and|but)\s+my\b", value, maxsplit=1, flags=re.I)[0].strip(" \t\r\n.,;:-")
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if len(parts) >= 3:
        return {"city": parts[0], "state": parts[1], "country": parts[2]}
    if len(parts) == 2:
        return {"city": parts[0], "state": parts[1]}
    if parts:
        return {"city": parts[0]}
    return {}


def _extract_profile_patch(message: str) -> dict[str, Any]:
    patch: dict[str, Any] = {}

    if email := EMAIL_RE.search(message):
        patch["email"] = email.group(0)

    if phone := PHONE_RE.search(message):
        patch["phone"] = phone.group(0).strip()

    for match in URL_RE.finditer(message):
        url = _clean_url(match.group(1))
        low = url.lower()
        if "linkedin" in low:
            patch["linkedin_url"] = url
        elif "github" in low:
            patch["github_url"] = url
        elif "portfolio" not in patch:
            patch["portfolio_url"] = url

    if full_name := _extract_named_value(
        message,
        [
            r"(?:full name is|my name is|name is)\s+([A-Za-z][A-Za-z'. -]{1,80})",
        ],
    ):
        cleaned = re.sub(r"\s+", " ", full_name).strip()
        parts = cleaned.split()
        patch["full_name"] = cleaned
        if parts:
            patch["first_name"] = parts[0]
            if len(parts) > 1:
                patch["last_name"] = " ".join(parts[1:])

    if first_name := _extract_named_value(message, [r"(?:first name is)\s+([A-Za-z][A-Za-z'. -]{0,40})"]):
        patch["first_name"] = first_name
    if last_name := _extract_named_value(message, [r"(?:last name is)\s+([A-Za-z][A-Za-z'. -]{0,60})"]):
        patch["last_name"] = last_name

    if location := _extract_named_value(
        message,
        [
            r"(?:based in|located in|live in|i'm in|i am in)\s+([A-Za-z .'-]+(?:,\s*[A-Za-z .'-]+){0,2}?)(?=\s+(?:and|but)\s+my\b|[.;\n]|$)",
            r"(?:city is)\s+([A-Za-z .'-]+)",
        ],
    ):
        patch.update(_parse_location(location))

    if state := _extract_named_value(message, [r"(?:state is)\s+([A-Za-z .'-]+)"]):
        patch["state"] = state
    if country := _extract_named_value(message, [r"(?:country is)\s+([A-Za-z .'-]+)"]):
        patch["country"] = country
    if postal := _extract_named_value(message, [r"(?:zip is|postal code is|zipcode is)\s+([A-Za-z0-9 -]+)"]):
        patch["postal_code"] = postal

    if current_company := _extract_named_value(message, [r"(?:current company is|company is)\s+([^.;\n]+)"]):
        patch["current_company"] = current_company
    if current_title := _extract_named_value(message, [r"(?:current title is|title is)\s+([^.;\n]+)"]):
        patch["current_title"] = current_title

    if school := _extract_named_value(message, [r"(?:school is|university is|college is)\s+([^.;\n]+)"]):
        patch["school"] = school
    if degree := _extract_named_value(message, [r"(?:degree is)\s+([^.;\n]+)"]):
        patch["degree"] = degree
    if major := _extract_named_value(message, [r"(?:major is|field of study is)\s+([^.;\n]+)"]):
        patch["major"] = major

    if pronouns := _extract_named_value(message, [r"(?:pronouns are|pronouns is)\s+([^.;\n]+)"]):
        patch["pronouns"] = pronouns
    if gender := _extract_named_value(message, [r"(?:gender is)\s+([^.;\n]+)"]):
        patch["gender"] = gender

    if preferred_titles := _extract_named_value(
        message,
        [r"(?:preferred titles are|target roles are|preferred roles are)\s+([^.;\n]+)"],
    ):
        patch["preferred_titles"] = [item.strip() for item in preferred_titles.split(",") if item.strip()]

    low = message.lower()
    if "prefer remote" in low or "remote only" in low:
        patch["remote_preference"] = "remote"
    elif "prefer hybrid" in low:
        patch["remote_preference"] = "hybrid"
    elif "prefer onsite" in low or "prefer on-site" in low:
        patch["remote_preference"] = "onsite"
    elif "open to any work setup" in low or "open to anything" in low:
        patch["remote_preference"] = "any"

    if "not willing to relocate" in low or "don't want to relocate" in low:
        patch["willing_to_relocate"] = False
    elif "willing to relocate" in low or "open to relocate" in low:
        patch["willing_to_relocate"] = True

    if "do not need sponsorship" in low or "don't need sponsorship" in low or "no sponsorship needed" in low:
        patch["needs_sponsorship"] = False
    elif "need sponsorship" in low or "require sponsorship" in low:
        patch["needs_sponsorship"] = True

    if "u.s. citizen" in low or "us citizen" in low:
        patch["work_auth_status"] = "us_citizen"
    elif "green card" in low:
        patch["work_auth_status"] = "green_card"
    elif "h1b" in low or "h-1b" in low:
        patch["work_auth_status"] = "h1b"
    elif "f1 opt" in low or "f-1 opt" in low:
        patch["work_auth_status"] = "f1_opt"
    elif "f1 cpt" in low or "f-1 cpt" in low:
        patch["work_auth_status"] = "f1_cpt"

    if years := _extract_named_value(message, [r"(?:years of experience is|years experience is|experience is)\s+(\d{1,2})"]):
        patch["years_experience"] = int(years)

    return patch


def _maybe_save_answer(message: str) -> dict[str, Any] | None:
    patterns = [
        r"(?:remember|save)\s+(?:this\s+)?answer[:\s]+(.+?)\s*(?:->|=>|=)\s*(.+)$",
        r"(?:question)\s*:\s*(.+?)\s*(?:answer)\s*:\s*(.+)$",
    ]
    for pattern in patterns:
        m = re.search(pattern, message, re.I | re.S)
        if not m:
            continue
        question = re.sub(r"\s+", " ", m.group(1)).strip()
        answer = re.sub(r"\s+", " ", m.group(2)).strip()
        if question and answer:
            result = db.save_answer(question, answer)
            result["action"] = "save_answer"
            result["question"] = question
            result["answer"] = answer
            return result
    return None


def _maybe_mark_complete(message: str) -> dict[str, Any] | None:
    low = message.lower()
    if not any(token in low for token in ("mark", "submitted", "complete", "done")):
        return None
    app_id = APP_ID_RE.search(message)
    if not app_id:
        return None
    application_id = app_id.group(0)
    ok = db.update_application(
        application_id,
        status="submitted",
        completed_at=datetime.now(timezone.utc).isoformat(),
    )
    return {
        "ok": ok,
        "action": "mark_complete",
        "application_id": application_id,
        "status": "submitted" if ok else "unchanged",
    }


def apply_chat_update(message: str) -> dict[str, Any]:
    """Parse a natural-language update request and persist the result."""
    message = (message or "").strip()
    if not message:
        raise ValueError("message is required")

    changes: list[dict[str, Any]] = []

    answer_result = _maybe_save_answer(message)
    if answer_result:
        changes.append(answer_result)

    complete_result = _maybe_mark_complete(message)
    if complete_result:
        changes.append(complete_result)

    patch = _extract_profile_patch(message)
    if patch:
        profile = db.update_profile(patch)
        changes.append(
            {
                "ok": True,
                "action": "update_profile",
                "patch": patch,
                "profile": profile,
            }
        )

    if not changes:
        return {
            "ok": False,
            "message": (
                "I couldn't tell what to update from that message. "
                "Try a more explicit update like 'Update my Instaply profile: "
                "I'm based in New York and my LinkedIn is ...' or "
                "'Remember this answer: Are you legally authorized to work in the US? -> Yes'."
            ),
        }

    return {
        "ok": True,
        "applied": changes,
        "message": "Instaply saved the update locally.",
    }
