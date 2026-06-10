import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import pytest  # noqa: E402
from backend.services.resume_tailoring_audit import (  # noqa: E402
    ResumeTailoringError,
    audit_tailored_resume,
    require_strong_tailoring,
)


MASTER_RESUME = {
    "experience": [
        {
            "company": "Fulcrum Digital",
            "title": "Business Analyst Intern",
            "dates": "Feb 2026 - May 2026",
            "location": "New York, NY",
            "bullets": ["Built RFP pricing models and risk assumptions for financial services clients."],
        },
        {
            "company": "NextAML LLC",
            "title": "Strategy Intern",
            "dates": "Jan 2026 - Apr 2026",
            "location": "New York, NY",
            "bullets": ["Ran SR 11-7 model validation and governance documentation for a bank client."],
        },
        {
            "company": "NYU AI Sandbox",
            "title": "Program Lead",
            "dates": "Jan 2026 - May 2026",
            "location": "New York, NY",
            "bullets": ["Built an AI agent governance audit tool with LangChain and vector databases."],
        },
    ],
    "projects": [
        {
            "name": "Instaply",
            "summary": "Job application agent with Greenhouse, Lever, and SmartRecruiters adapters.",
            "tags": ["ai-agents", "python"],
        }
    ],
    "publications": [],
    "skills": {"Tools": ["Python", "SQL", "AI governance", "model risk", "Power BI"]},
}


JD_TEXT = """
Business Analyst Intern, AI Governance and Risk Operations.
The team needs SQL, Python, AI governance, model risk, compliance analytics,
requirements analysis, dashboarding, and financial services risk documentation.
"""


def test_strong_tailored_resume_passes_audit():
    tailored = {
        "selected_summary": (
            "Business Analyst intern focused on AI governance, model risk, SQL/Python analytics, "
            "and financial services risk documentation."
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
                "bullets": [
                    {"text": "Ran model risk validation and governance documentation for bank compliance workflows."}
                ],
            },
            {
                "company": "NYU AI Sandbox",
                "title": "Program Lead",
                "bullets": [
                    {"text": "Built an AI governance audit tool for agent risk testing using Python and LangChain."}
                ],
            },
        ],
        "projects": [{"name": "Instaply", "summary": "AI application agent with ATS adapters."}],
        "skills_display": [
            {"label": "Risk Analytics", "items": ["SQL", "Python", "AI governance", "model risk", "Power BI"]}
        ],
    }

    audit = require_strong_tailoring(
        jd_text=JD_TEXT,
        tailored_resume=tailored,
        master_resume=MASTER_RESUME,
        company_context={"company": "ExampleCo", "role": "Business Analyst Intern"},
    )

    assert audit["passed"] is True
    assert audit["score"] >= 75
    assert "ai" in audit["matched_role_signals"]
    assert "governance" in audit["matched_role_signals"]


def test_generic_resume_fails_audit():
    tailored = {
        "selected_summary": "Analytics candidate with strong communication skills.",
        "experience": [
            {"company": "Fulcrum Digital", "title": "Business Analyst Intern", "bullets": [{"text": "Supported teams and helped with projects."}]}
        ],
        "projects": [],
        "skills_display": [{"label": "Tools", "items": ["Excel"]}],
    }

    audit = audit_tailored_resume(
        jd_text=JD_TEXT,
        tailored_resume=tailored,
        master_resume=MASTER_RESUME,
        company_context={"company": "ExampleCo", "role": "Business Analyst Intern"},
    )

    assert audit["passed"] is False
    assert any("keyword coverage" in blocker for blocker in audit["blockers"])
    with pytest.raises(ResumeTailoringError):
        require_strong_tailoring(
            jd_text=JD_TEXT,
            tailored_resume=tailored,
            master_resume=MASTER_RESUME,
            company_context={"company": "ExampleCo", "role": "Business Analyst Intern"},
        )
