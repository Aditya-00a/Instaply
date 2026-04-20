from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
PROMPTS_DIR = ROOT_DIR / "backend" / "prompts"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_profile() -> dict[str, Any]:
    return read_json(DATA_DIR / "profile.json")


def load_master_resume() -> dict[str, Any]:
    return read_json(DATA_DIR / "master-resume.json")


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")

