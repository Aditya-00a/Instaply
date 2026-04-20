import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import doctor  # noqa: E402
from backend.services.files import normalize_profile  # noqa: E402
from profile_wizard import ProfileAnswers, to_profile_json  # noqa: E402


def test_normalize_profile_supports_nested_targets():
    normalized = normalize_profile(
        {
            "name": "Smoke Test User",
            "targets": {
                "roles": ["Data Analyst", "Risk Analyst"],
                "locations": ["Remote", "New York"],
            },
        }
    )

    assert normalized["target_roles"] == ["Data Analyst", "Risk Analyst"]
    assert normalized["target_locations"] == ["Remote", "New York"]
    assert normalized["location"] == ["Remote", "New York"]


def test_profile_wizard_keeps_legacy_target_aliases():
    profile = to_profile_json(
        ProfileAnswers(
            first_name="Smoke",
            last_name="Test",
            legal_name="Smoke Test",
            email="smoke@example.com",
            city="New York",
            state="NY",
            target_roles=["Data Analyst"],
            target_locations=["Remote"],
        )
    )

    assert profile["targets"]["roles"] == ["Data Analyst"]
    assert profile["target_roles"] == ["Data Analyst"]
    assert profile["location"] == ["Remote"]


def test_doctor_accepts_legacy_profile_schema(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "profile.json").write_text(
        json.dumps(
            {
                "name": "Smoke Test User",
                "contact": {"email": "smoke@example.com"},
                "target_roles": ["Data Analyst"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(doctor, "DATA_DIR", data_dir)

    result = doctor.check_profile_json()

    assert result.ok
