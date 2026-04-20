from __future__ import annotations

import tomllib
from pathlib import Path


def test_worker_extra_declares_llm_dependencies():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))

    worker = data["project"]["optional-dependencies"]["worker"]

    assert any(dep.startswith("playwright") for dep in worker)
    assert any(dep.startswith("openai") for dep in worker)
    assert any(dep.startswith("tenacity") for dep in worker)
