import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import pytest  # noqa: E402
from backend.db.database import get_connection, init_db  # noqa: E402
from backend.services.application_review_gate import (  # noqa: E402
    create_or_update_review_request,
    record_review_decision,
)
from backend.services.auto_apply import submit_approved_review  # noqa: E402


JD_TEXT = """
Business Analyst Intern for AI governance, model risk, compliance analytics,
SQL, Python, dashboarding, financial services risk documentation, and business requirements.
"""


MASTER_RESUME = {
    "name": "Aditya Sakhale",
    "contact": {"email": "aditya@example.com"},
    "experience": [
        {
            "company": "Fulcrum Digital",
            "title": "Business Analyst Intern",
            "dates": "Feb 2026 - May 2026",
            "location": "New York, NY",
            "bullets": ["Built pricing and risk dashboards for financial services RFP analysis."],
        },
        {
            "company": "NextAML LLC",
            "title": "Strategy Intern",
            "dates": "Jan 2026 - Apr 2026",
            "location": "New York, NY",
            "bullets": ["Ran model risk validation and compliance governance documentation."],
        },
        {
            "company": "NYU AI Sandbox",
            "title": "Program Lead",
            "dates": "Jan 2026 - May 2026",
            "location": "New York, NY",
            "bullets": ["Built an AI governance audit tool with Python."],
        },
    ],
    "projects": [{"name": "Instaply", "summary": "AI application agent.", "tags": ["ai"]}],
    "publications": [],
    "skills": {"Tools": ["SQL", "Python", "AI governance", "model risk", "Power BI"]},
}


TAILORED_RESUME = {
    "selected_summary": (
        "Business Analyst intern focused on AI governance, model risk, SQL/Python analytics, "
        "financial services risk documentation, and compliance dashboarding."
    ),
    "experience": [
        {
            "company": "Fulcrum Digital",
            "title": "Business Analyst Intern",
            "bullets": [
                {"text": "Built SQL-backed pricing and risk dashboards for financial services RFP analysis."},
                {"text": "Mapped business requirements into controls, assumptions, and delivery risks."},
            ],
        },
        {
            "company": "NextAML LLC",
            "title": "Strategy Intern",
            "bullets": [{"text": "Ran model risk validation and compliance governance documentation."}],
        },
        {
            "company": "NYU AI Sandbox",
            "title": "Program Lead",
            "bullets": [{"text": "Built an AI governance audit tool using Python and LangChain."}],
        },
    ],
    "projects": [{"name": "Instaply", "summary": "AI application agent with ATS adapters."}],
    "skills_display": [{"label": "Risk Analytics", "items": ["SQL", "Python", "AI governance", "model risk"]}],
}


def _seed_approved_flow_db(tmp_path: Path) -> tuple[Path, str, str]:
    db_path = init_db(tmp_path / "jobs.db")
    resume_file = tmp_path / "resume.docx"
    resume_file.write_text("resume", encoding="utf-8")
    cover_file = tmp_path / "cover.docx"
    cover_file.write_text("cover", encoding="utf-8")
    job_id = "job-1"
    resume_id = "resume-1"
    cover_id = "cover-1"
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO jobs (
              id, title, company, url, status, match_score, resume_version, cover_letter_version, jd_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                "Business Analyst Intern",
                "ExampleCo",
                "https://example.com/job",
                "packet_generated",
                0.92,
                resume_id,
                cover_id,
                JD_TEXT,
            ),
        )
        conn.execute(
            """
            INSERT INTO resume_generations (
              id, role_bucket, jd_hash, jd_text, tailored_resume_json, selection_summary_json, docx_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                resume_id,
                "risk_analytics",
                hashlib.sha256(JD_TEXT.encode("utf-8")).hexdigest(),
                JD_TEXT,
                json.dumps(TAILORED_RESUME),
                "{}",
                str(resume_file),
            ),
        )
        conn.execute(
            """
            INSERT INTO cover_letter_generations (
              id, role_bucket, jd_hash, jd_text, cover_letter_text, selection_summary_json, docx_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cover_id,
                "risk_analytics",
                hashlib.sha256(JD_TEXT.encode("utf-8")).hexdigest(),
                JD_TEXT,
                "Cover letter",
                "{}",
                str(cover_file),
            ),
        )
        conn.commit()

    review = create_or_update_review_request(
        job_id=job_id,
        screenshot_path=str(tmp_path / "ready.png"),
        platform="greenhouse",
        filled_fields=["first_name", "email", "resume"],
        needs_review=[],
        db_path=db_path,
    )
    return db_path, job_id, review["id"]


@pytest.mark.asyncio
async def test_submit_approved_review_requires_approval(tmp_path, monkeypatch):
    db_path, _, review_id = _seed_approved_flow_db(tmp_path)

    async def should_not_call(**kwargs):
        raise AssertionError("autofill should not be called before approval")

    result = await submit_approved_review(review_id, db_path=db_path, autofill_func=should_not_call)

    assert result["status"] == "skipped"
    assert result["reason"] == "review_not_approved"


@pytest.mark.asyncio
async def test_submit_approved_review_submits_and_tracks(tmp_path, monkeypatch):
    db_path, job_id, review_id = _seed_approved_flow_db(tmp_path)
    record_review_decision(review_id, decision="approved", db_path=db_path)
    monkeypatch.setattr("backend.services.auto_apply.load_master_resume", lambda: MASTER_RESUME)
    monkeypatch.setattr("backend.services.auto_apply.load_profile", lambda: {"contact": {}})
    calls = {}

    async def fake_autofill(**kwargs):
        calls.update(kwargs)
        return {
            "submitted": True,
            "status": "submitted",
            "platform_detected": "greenhouse",
            "filled_fields": ["first_name", "email", "resume"],
            "screenshot_path": "ready.png",
            "post_submit_screenshot": "submitted.png",
        }

    result = await submit_approved_review(review_id, db_path=db_path, autofill_func=fake_autofill)

    assert result["status"] == "submitted"
    assert calls["submit_approved"] is True
    with get_connection(db_path) as conn:
        job = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
        tracking_count = conn.execute("SELECT COUNT(*) AS c FROM application_tracking").fetchone()["c"]
        review = conn.execute("SELECT status FROM application_review_requests WHERE id = ?", (review_id,)).fetchone()
    assert job["status"] == "applied"
    assert tracking_count == 1
    assert review["status"] == "submitted"

