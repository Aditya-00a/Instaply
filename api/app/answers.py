"""Answer management — let users teach the agent unknown questions.

Flow:
  1. Submitter encounters question it can't answer from profile
  2. Saves question to applications.submission_log["needs_review"]
  3. Frontend shows the questions on the application card
  4. User types an answer, hits Save
  5. POST /answers/save stores it in answers table (per-user)
  6. Next time same question appears anywhere, agent reuses the answer
"""
from __future__ import annotations

import hashlib
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Request

from .auth import current_user_id
from .db import service_client
from .ratelimit import rate_limit

log = logging.getLogger("answers")
router = APIRouter(tags=["answers"])


def _normalize_question(q: str) -> str:
    """Normalize question text for hashing. Strip whitespace, lowercase, drop punctuation."""
    q = (q or "").lower().strip()
    q = re.sub(r"\s+", " ", q)
    q = re.sub(r"[^\w\s]", "", q)
    return q


def _question_hash(q: str) -> str:
    return hashlib.sha256(_normalize_question(q).encode("utf-8")).hexdigest()[:32]


@router.post("/answers/save")
async def save_answer(
    request: Request,
    user_id: str = Depends(current_user_id),
    _rl: None = rate_limit("save_answer", per_min=30),
):
    """Save (or update) the user's answer to a question."""
    body = await request.json()
    question = (body.get("question") or "").strip()
    answer = (body.get("answer") or "").strip()
    company = body.get("company_slug") or None
    application_id = body.get("application_id")

    if not question or not answer:
        raise HTTPException(400, "question and answer required")

    db = service_client()
    qhash = _question_hash(question)

    # Upsert by (user_id, question_hash)
    existing = (
        db.table("answers")
        .select("id, times_used")
        .eq("user_id", user_id)
        .eq("question_hash", qhash)
        .limit(1)
        .execute()
    )
    if existing.data:
        # Update text in case user is rewording
        db.table("answers").update({
            "answer_text": answer,
            "question_text": question,
            "company_slug": company,
        }).eq("id", existing.data[0]["id"]).execute()
        ans_id = existing.data[0]["id"]
    else:
        ins = db.table("answers").insert({
            "user_id": user_id,
            "question_hash": qhash,
            "question_text": question,
            "answer_text": answer,
            "company_slug": company,
            "times_used": 0,
        }).execute()
        ans_id = ins.data[0]["id"] if ins.data else None

    # If this answer was for a specific application that's failed/needs_review,
    # re-queue it so the submitter tries again with the new answer.
    if application_id:
        db.table("applications").update({
            "status": "queued",
            "error_message": None,
            "started_at": None,
        }).eq("id", application_id).eq("user_id", user_id).execute()

    return {"ok": True, "answer_id": ans_id, "requeued": bool(application_id)}


@router.get("/applications/{app_id}/needs-review")
async def get_needs_review(
    app_id: str,
    user_id: str = Depends(current_user_id),
    _rl: None = rate_limit("needs_review", per_min=60),
):
    """Return the unanswered questions for an application, with any saved answers pre-filled."""
    db = service_client()
    app = (
        db.table("applications")
        .select("id, status, submission_log, jobs(title, company_name, company_slug)")
        .eq("id", app_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    if not app.data:
        raise HTTPException(404, "Application not found")

    log_data = app.data.get("submission_log")
    questions: list[dict] = []
    if log_data:
        try:
            import json
            parsed = json.loads(log_data) if isinstance(log_data, str) else log_data
            review = parsed.get("needs_review", [])
            for r in review:
                if isinstance(r, dict):
                    q_text = r.get("question") or r.get("normalized_key") or ""
                    if q_text:
                        questions.append({"question": q_text})
        except Exception:
            pass

    # For each question, check if user already saved an answer
    if questions:
        for q in questions:
            qhash = _question_hash(q["question"])
            saved = (
                db.table("answers")
                .select("answer_text")
                .eq("user_id", user_id)
                .eq("question_hash", qhash)
                .limit(1)
                .execute()
            )
            if saved.data:
                q["saved_answer"] = saved.data[0]["answer_text"]

    return {
        "application_id": app_id,
        "questions": questions,
        "company_slug": (app.data.get("jobs") or {}).get("company_slug"),
    }
