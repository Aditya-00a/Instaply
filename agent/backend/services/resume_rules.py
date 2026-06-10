from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.services.files import read_json

ROOT_DIR = Path(__file__).resolve().parents[2]
RULES_PATH = ROOT_DIR / "config" / "resume_rules.json"
# Personal tailoring rules live OUTSIDE the tracked config so they never
# reach the public repo: data/resume_rules.local.json (gitignored) is
# deep-merged over the shipped defaults when present.
LOCAL_RULES_PATH = ROOT_DIR / "data" / "resume_rules.local.json"


def _deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_resume_rules() -> dict[str, Any]:
    rules = read_json(RULES_PATH)
    if LOCAL_RULES_PATH.exists():
        try:
            rules = _deep_merge(rules, read_json(LOCAL_RULES_PATH))
        except Exception:
            pass
    return rules


def resolve_rule_set(role_type: str) -> dict[str, Any]:
    rules = load_resume_rules()
    role_rules = rules.get("role_rules", {})
    return role_rules.get(role_type) or role_rules.get("ai_product", {})

