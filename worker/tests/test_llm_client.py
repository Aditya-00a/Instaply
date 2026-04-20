"""Tests for the worker's LLM client (Cerebras backend).

We don't make real API calls — the OpenAI Python SDK is patched at
construction time via env-var manipulation, and we verify:

  - the resolved API key precedence (CEREBRAS_API_KEY > OPENAI_API_KEY)
  - the default base URL points at Cerebras, not NIM
  - the default model names are Cerebras-hosted Llama variants
  - the per-task fallback chain
  - the backward-compat alias `NimClient is CerebrasClient`
  - constructor raises a clear error when no key is set anywhere
"""
from __future__ import annotations

import os

import pytest

from worker.autofill import llm as llm_mod
from worker.autofill.llm import (
    DEFAULT_BASE_URL,
    DEFAULT_PRIMARY_MODEL,
    DEFAULT_SECONDARY_MODEL,
    CerebrasClient,
    LlmTask,
    NimClient,
    _build_prompt,
    _resolve_api_key,
)
from worker.autofill.models import FieldCandidate, FieldType, UserProfile


# ─── Backward-compat alias ───────────────────────────────────────
def test_nim_client_alias_is_cerebras_client():
    """Old `NimClient` import must still resolve to the new class."""
    assert NimClient is CerebrasClient


# ─── Default constants point at Cerebras ─────────────────────────
def test_default_base_url_is_cerebras():
    assert DEFAULT_BASE_URL == "https://api.cerebras.ai/v1"
    # Sanity — no NIM/Nvidia leftovers
    assert "nvidia" not in DEFAULT_BASE_URL.lower()
    assert "nim" not in DEFAULT_BASE_URL.lower()


def test_defaults_are_models_cerebras_actually_serves():
    # Both verified against the live /v1/models endpoint on the
    # production Cerebras account on 2026-04-17. Other candidates
    # (gpt-oss-120b, zai-glm-4.7, llama-3.3-70b, llama3.3-70b) all
    # 404 against this account.
    assert DEFAULT_PRIMARY_MODEL == "qwen-3-235b-a22b-instruct-2507"
    assert DEFAULT_SECONDARY_MODEL == "llama3.1-8b"
    # Guard against accidentally regressing to a known-bad name
    assert DEFAULT_PRIMARY_MODEL != "llama-3.3-70b"
    assert "nemotron" not in DEFAULT_PRIMARY_MODEL.lower()
    assert "kimi" not in DEFAULT_SECONDARY_MODEL.lower()


# ─── Env-var resolution ──────────────────────────────────────────
def test_resolve_api_key_prefers_explicit_arg(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "from-cerebras-env")
    monkeypatch.setenv("OPENAI_API_KEY", "from-openai-env")
    assert _resolve_api_key("explicit-key") == "explicit-key"


def test_resolve_api_key_uses_cerebras_env_when_no_arg(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "from-cerebras-env")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert _resolve_api_key(None) == "from-cerebras-env"


def test_resolve_api_key_falls_back_to_openai_env(monkeypatch):
    """Matches the production API pattern in api/app/auto_apply.py and
    api/app/resume_analyzer.py — a single OPENAI_API_KEY can power both."""
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key-as-cerebras")
    assert _resolve_api_key(None) == "openai-key-as-cerebras"


def test_resolve_api_key_returns_empty_when_nothing_set(monkeypatch):
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert _resolve_api_key(None) == ""


def test_constructor_raises_when_no_key_anywhere(monkeypatch):
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError) as exc:
        CerebrasClient()
    msg = str(exc.value)
    # Error message should mention the right env vars so operators know
    # what to set; no NIM references.
    assert "CEREBRAS_API_KEY" in msg
    assert "OPENAI_API_KEY" in msg
    assert "NVIDIA" not in msg.upper()


def test_constructor_does_not_read_legacy_nim_env(monkeypatch):
    """NVIDIA_NIM_API_KEY alone must NOT satisfy the constructor —
    operators get a clean failure prompting them to migrate."""
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "legacy-nim-key")
    with pytest.raises(RuntimeError):
        CerebrasClient()


# ─── Constructor wiring ──────────────────────────────────────────
def test_constructor_uses_default_base_url_and_models(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "k")
    monkeypatch.delenv("CEREBRAS_BASE_URL", raising=False)
    monkeypatch.delenv("CEREBRAS_PRIMARY_MODEL", raising=False)
    monkeypatch.delenv("CEREBRAS_SECONDARY_MODEL", raising=False)
    c = CerebrasClient()
    assert c.base_url == DEFAULT_BASE_URL
    assert c.primary == DEFAULT_PRIMARY_MODEL
    assert c.secondary == DEFAULT_SECONDARY_MODEL


def test_constructor_respects_env_overrides(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "k")
    monkeypatch.setenv("CEREBRAS_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("CEREBRAS_PRIMARY_MODEL", "custom-primary")
    monkeypatch.setenv("CEREBRAS_SECONDARY_MODEL", "custom-secondary")
    c = CerebrasClient()
    assert c.base_url == "https://example.test/v1"
    assert c.primary == "custom-primary"
    assert c.secondary == "custom-secondary"


def test_constructor_arg_overrides_env(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "env-key")
    monkeypatch.setenv("CEREBRAS_BASE_URL", "https://from-env.test/v1")
    c = CerebrasClient(
        api_key="explicit-key",
        base_url="https://from-arg.test/v1",
        primary_model="arg-primary",
        secondary_model="arg-secondary",
    )
    assert c.base_url == "https://from-arg.test/v1"
    assert c.primary == "arg-primary"
    assert c.secondary == "arg-secondary"


# ─── Task → model fallback chain ─────────────────────────────────
def test_chain_for_long_text_leads_with_primary(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "k")
    c = CerebrasClient(primary_model="P", secondary_model="S")
    chain = c._chain_for_task(LlmTask.LONG_TEXT)
    assert chain == ["P", "S"]


def test_chain_for_short_text_leads_with_secondary(monkeypatch):
    """Small/fast model goes first for short answers (cost + latency win)."""
    monkeypatch.setenv("CEREBRAS_API_KEY", "k")
    c = CerebrasClient(primary_model="P", secondary_model="S")
    assert c._chain_for_task(LlmTask.SHORT_TEXT) == ["S", "P"]


def test_chain_for_pick_option_leads_with_secondary(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "k")
    c = CerebrasClient(primary_model="P", secondary_model="S")
    assert c._chain_for_task(LlmTask.PICK_OPTION) == ["S", "P"]


def test_chain_for_yes_no_leads_with_secondary(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "k")
    c = CerebrasClient(primary_model="P", secondary_model="S")
    assert c._chain_for_task(LlmTask.YES_NO) == ["S", "P"]


def test_chain_no_longer_includes_a_third_model(monkeypatch):
    """Cerebras only hosts Llama variants — the old NIM 3-model chain
    (primary → secondary → reasoning) is intentionally collapsed to two."""
    monkeypatch.setenv("CEREBRAS_API_KEY", "k")
    c = CerebrasClient()
    for task in LlmTask:
        chain = c._chain_for_task(task)
        assert len(chain) == 2, f"{task} chain should be length 2, got {chain}"


# ─── No NIM env names left in the module ─────────────────────────
def test_module_does_not_reference_nvidia_nim_env_names():
    """Source-level guarantee: no NVIDIA_NIM_* env-var lookups remain."""
    src = open(llm_mod.__file__, encoding="utf-8").read()
    assert "NVIDIA_NIM_API_KEY" not in src
    assert "NVIDIA_NIM_BASE_URL" not in src
    assert "NVIDIA_NIM_PRIMARY_MODEL" not in src
    assert "NVIDIA_NIM_SECONDARY_MODEL" not in src
    assert "NVIDIA_NIM_REASONING_MODEL" not in src


def test_build_prompt_includes_resume_grounding_when_available():
    cand = FieldCandidate(
        dom_id="why-company",
        field_type=FieldType.TEXTAREA,
        label="Why are you interested in this role?",
        required=True,
    )
    profile = UserProfile(
        user_id="u1",
        first_name="Jordan",
        last_name="Lee",
        full_name="Jordan Lee",
        email="jordan.lee@example.com",
        resume_parsed_json={
            "education": {"degree": "MS", "major": "Data Science", "school": "NYU"},
            "titles_held": ["Data Analyst"],
        },
        resume_text_excerpt="Experience: Data Analyst at Fulcrum Digital. Education: MS in Data Science at NYU.",
    )

    prompt = _build_prompt(LlmTask.LONG_TEXT, cand, profile)

    assert "STRUCTURED RESUME EVIDENCE" in prompt
    assert "RAW RESUME TEXT EXCERPT" in prompt
    assert "Data Analyst at Fulcrum Digital" in prompt
    assert '"major": "Data Science"' in prompt
