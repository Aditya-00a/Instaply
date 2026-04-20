from __future__ import annotations

from instaply_mcp import db
from instaply_mcp import updates


def test_apply_chat_update_profile_patch(monkeypatch, tmp_path):
    monkeypatch.setenv("INSTAPLY_DATA_DIR", str(tmp_path))

    result = updates.apply_chat_update(
        "Update my Instaply profile: I'm based in New York, NY and my LinkedIn is linkedin.com/in/adityasakhale"
    )

    assert result["ok"] is True
    profile_update = next(item for item in result["applied"] if item["action"] == "update_profile")
    assert profile_update["patch"]["city"] == "New York"
    assert profile_update["patch"]["state"] == "NY"
    assert profile_update["patch"]["linkedin_url"] == "https://linkedin.com/in/adityasakhale"


def test_apply_chat_update_save_answer(monkeypatch, tmp_path):
    monkeypatch.setenv("INSTAPLY_DATA_DIR", str(tmp_path))

    result = updates.apply_chat_update(
        "Remember this answer: Are you legally authorized to work in the United States? -> Yes"
    )

    assert result["ok"] is True
    saved = next(item for item in result["applied"] if item["action"] == "save_answer")
    assert saved["answer"] == "Yes"
    answers = db.list_answers()
    assert answers[0]["answer_text"] == "Yes"


def test_apply_chat_update_mark_complete(monkeypatch, tmp_path):
    monkeypatch.setenv("INSTAPLY_DATA_DIR", str(tmp_path))

    job_id = db.upsert_job(
        source="manual",
        external_id="test:123",
        company_name="Acme",
        title="Analyst",
        apply_url="https://example.com/job",
    )
    queued = db.queue_application(job_id)

    result = updates.apply_chat_update(
        f"Mark application {queued['application_id']} as submitted"
    )

    assert result["ok"] is True
    completed = next(item for item in result["applied"] if item["action"] == "mark_complete")
    assert completed["status"] == "submitted"
    apps = db.list_applications(limit=5)
    assert apps[0]["status"] == "submitted"
