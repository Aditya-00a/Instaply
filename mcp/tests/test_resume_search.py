from __future__ import annotations

import asyncio

from instaply_mcp import db
from instaply_mcp import resume
from instaply_mcp import search


def test_import_resume_text_extracts_grounded_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("INSTAPLY_DATA_DIR", str(tmp_path))
    sample = """
Aditya Sakhale
aditya@example.com
+1 (415) 555-0100
linkedin.com/in/adityasakhale

Education
New York University School of Professional Studies
Master of Science in Management & Analytics (Risk Analytics)

Experience
AI Risk Management Intern
AI Business Analyst Intern
Data Scientist

Skills
Python, SQL, Excel, Risk Analytics, Automation
"""
    result = resume.import_resume(resume_text=sample)

    assert result["ok"] is True
    assert result["profile"]["full_name"] == "Aditya Sakhale"
    assert result["profile"]["email"] == "aditya@example.com"
    assert result["profile"]["linkedin_url"] == "https://linkedin.com/in/adityasakhale"
    assert result["profile"]["degree"] == "Master's"
    assert "Management & Analytics" in (result["profile"]["major"] or "")
    assert "Python" in result["extracted"]["skills"]
    assert "SQL" in result["extracted"]["skills"]
    assert "Risk Analyst" in result["extracted"]["role_targets"]
    assert "Software Engineer" not in result["extracted"]["role_targets"]


def test_search_jobs_derives_queries_and_ranks_matches(monkeypatch, tmp_path):
    monkeypatch.setenv("INSTAPLY_DATA_DIR", str(tmp_path))
    db.update_profile(
        {
            "city": "New York",
            "state": "NY",
            "country": "United States",
            "current_title": "AI Risk Management Intern",
            "major": "Management & Analytics (Risk Analytics)",
            "extracted_skills": {
                "skills": ["Python", "SQL", "Risk Analysis"],
                "titles_held": ["AI Risk Management Intern", "Data Scientist"],
                "role_targets": ["Risk Analyst", "Data Analyst"],
            },
        }
    )

    monkeypatch.setattr(
        search,
        "_search_jobspy_sync",
        lambda query, location, remote, limit: [
            {
                "external_id": f"jobspy:{query}:1",
                "title": "Risk Analyst",
                "company_name": "Acme",
                "company_slug": "acme",
                "location": "New York, NY",
                "remote": False,
                "apply_url": f"https://example.com/{query}/risk-analyst",
                "description": "Python SQL risk analysis role",
                "source": "greenhouse",
            }
        ],
    )
    async def _empty_themuse(query, location):
        return []

    async def _empty_arbeitnow(query):
        return []

    async def _empty_remotive(query):
        return []

    monkeypatch.setattr(search, "_search_themuse", _empty_themuse)
    monkeypatch.setattr(search, "_search_arbeitnow", _empty_arbeitnow)
    monkeypatch.setattr(search, "_search_remotive", _empty_remotive)

    result = asyncio.run(search.search_jobs(limit=5))

    assert result["ok"] is True
    assert "Risk Analyst" in result["derived_queries"]
    assert result["results"][0]["title"] == "Risk Analyst"
    assert result["results"][0]["match_score"] > 0.5
    assert result["results"][0]["job_id"]
