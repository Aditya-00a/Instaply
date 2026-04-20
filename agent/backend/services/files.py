from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
PROMPTS_DIR = ROOT_DIR / "backend" / "prompts"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    cleaned = str(value).strip()
    return [cleaned] if cleaned else []


def normalize_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Keep legacy and nested target fields aligned."""
    normalized = dict(profile)
    targets = dict(normalized.get("targets") or {})

    target_roles = _as_str_list(targets.get("roles") or normalized.get("target_roles"))
    target_locations = _as_str_list(
        targets.get("locations")
        or normalized.get("target_locations")
        or normalized.get("location")
    )

    targets["roles"] = target_roles
    targets["locations"] = target_locations
    normalized["targets"] = targets
    normalized["target_roles"] = target_roles
    normalized["target_locations"] = target_locations
    normalized["location"] = target_locations
    return normalized


def load_profile() -> dict[str, Any]:
    return normalize_profile(read_json(DATA_DIR / "profile.json"))


def load_master_resume() -> dict[str, Any]:
    return read_json(DATA_DIR / "master-resume.json")


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")
