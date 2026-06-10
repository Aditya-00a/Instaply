import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from backend.db.database import get_connection, init_db  # noqa: E402
from backend.services.application_review_gate import (  # noqa: E402
    create_or_update_review_request,
    list_review_requests,
    record_review_decision,
)


def test_review_gate_creates_updates_and_records_decision(tmp_path):
    db_path = init_db(tmp_path / "jobs.db")
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO jobs (id, title, company, url, match_score, status)
            VALUES ('job-1', 'Business Analyst Intern', 'ExampleCo', 'https://example.com/job', 0.91, 'packet_generated')
            """
        )
        conn.commit()

    first = create_or_update_review_request(
        job_id="job-1",
        screenshot_path="artifacts/one.png",
        platform="greenhouse",
        filled_fields=["first_name", "email"],
        needs_review=[{"question": "Confirm details", "normalized_key": "confirm_details"}],
        db_path=db_path,
    )
    second = create_or_update_review_request(
        job_id="job-1",
        screenshot_path="artifacts/two.png",
        platform="greenhouse",
        filled_fields=["first_name", "email", "resume"],
        needs_review=[],
        db_path=db_path,
    )

    assert first["id"] == second["id"]
    assert second["status"] == "pending_approval"
    assert second["screenshot_path"] == "artifacts/two.png"
    assert second["filled_fields"] == ["first_name", "email", "resume"]

    pending = list_review_requests(db_path=db_path)
    assert pending["count"] == 1

    approved = record_review_decision(second["id"], decision="approved", db_path=db_path)
    assert approved["status"] == "approved"
    assert approved["decision"] == "approved"

