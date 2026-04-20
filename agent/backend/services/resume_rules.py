from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.services.files import read_json

ROOT_DIR = Path(__file__).resolve().parents[2]
RULES_PATH = ROOT_DIR / "config" / "resume_rules.json"


def load_resume_rules() -> dict[str, Any]:
    return read_json(RULES_PATH)


def resolve_rule_set(role_type: str) -> dict[str, Any]:
    rules = load_resume_rules()
    role_rules = rules.get("role_rules", {})
    return role_rules.get(role_type) or role_rules.get("ai_product", {})

