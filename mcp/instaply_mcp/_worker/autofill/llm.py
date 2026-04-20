"""LLM fallback for the autofill engine.

Backend: Cerebras (api.cerebras.ai), the same provider Instaply's API
already uses for resume analysis and discovery scoring (see
`api/app/resume_analyzer.py` and `api/app/auto_apply.py`). Cerebras
exposes an OpenAI-compatible endpoint, so we keep using the `openai`
Python SDK with a custom `base_url`.

Per-task model routing with a short fallback chain so a transient
provider error doesn't halt an application run:
  - short_text  (names, single-line answers)        -> primary, secondary
  - long_text   ("why this role", cover letter)     -> primary, secondary
  - pick_option (dropdowns, radios)                 -> secondary, primary
  - yes_no      (binary radios)                     -> secondary, primary

Cerebras only hosts Llama variants in production today, so we no longer
need a separate "reasoning" model — the chain collapses to primary +
secondary. If a future Cerebras tier exposes a stronger model, set the
`CEREBRAS_PRIMARY_MODEL` env var and it'll be picked up at startup.

Backward compatibility: `NimClient` is preserved as a deprecated alias
for `CerebrasClient` so any pre-existing import keeps working.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from openai import OpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .models import FieldCandidate, FieldType, UserProfile

log = logging.getLogger(__name__)


# Defaults match the Cerebras setup the production API already uses.
DEFAULT_BASE_URL = "https://api.cerebras.ai/v1"
# Probed against the live Cerebras account on 2026-04-17: only
# `llama3.1-8b` and `qwen-3-235b-a22b-instruct-2507` return 200.
# Other names listed by /v1/models (gpt-oss-120b, zai-glm-4.7) return
# 404 — listed but not entitled. The previous default `llama-3.3-70b`
# was never valid on this account.
# Qwen 3 235B (22B active) is a MoE — strong for long-text generation
# while staying fast on Cerebras' wafer-scale inference.
DEFAULT_PRIMARY_MODEL = "qwen-3-235b-a22b-instruct-2507"
# Cerebras' canonical id for the 8B Llama model is `llama3.1-8b`
# (no dash between "3" and "1"). Using the dashed variant returns
# 404 Not Found from api.cerebras.ai/v1/chat/completions — confirmed
# in production canary logs on 2026-04-17.
DEFAULT_SECONDARY_MODEL = "llama3.1-8b"


class LlmTask(str, Enum):
    SHORT_TEXT = "short_text"
    LONG_TEXT = "long_text"
    PICK_OPTION = "pick_option"
    YES_NO = "yes_no"


@dataclass
class LlmAnswer:
    value: str
    confidence: float
    model: str
    reasoning: Optional[str] = None


def _pick_task(cand: FieldCandidate) -> LlmTask:
    if cand.field_type in (FieldType.SELECT, FieldType.RADIO) and cand.options:
        if len(cand.options) <= 3 and _looks_yes_no(cand.options):
            return LlmTask.YES_NO
        return LlmTask.PICK_OPTION
    if cand.field_type == FieldType.TEXTAREA:
        return LlmTask.LONG_TEXT
    if cand.max_length and cand.max_length > 250:
        return LlmTask.LONG_TEXT
    return LlmTask.SHORT_TEXT


def _looks_yes_no(options: list[str]) -> bool:
    low = {o.strip().lower() for o in options}
    return bool(low & {"yes", "no"}) or low == {"true", "false"}


def _resolve_api_key(explicit: Optional[str]) -> str:
    """Resolve the Cerebras API key with the same precedence the API uses.

    Priority: explicit ctor arg > CEREBRAS_API_KEY > OPENAI_API_KEY.
    The OPENAI fallback matches `api/app/auto_apply.py:177` and
    `api/app/resume_analyzer.py:65-69` so a single secret can power both
    the API and the worker if an operator chooses.
    """
    if explicit:
        return explicit
    return os.environ.get("CEREBRAS_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""


class CerebrasClient:
    """Thin wrapper over Cerebras' OpenAI-compatible chat endpoint with
    a primary→secondary model fallback chain.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        primary_model: Optional[str] = None,
        secondary_model: Optional[str] = None,
    ):
        api_key = _resolve_api_key(api_key)
        if not api_key:
            raise RuntimeError(
                "No LLM API key found. Set CEREBRAS_API_KEY (or OPENAI_API_KEY)."
            )
        base_url = base_url or os.environ.get("CEREBRAS_BASE_URL", DEFAULT_BASE_URL)
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.base_url = base_url
        self.primary = primary_model or os.environ.get(
            "CEREBRAS_PRIMARY_MODEL", DEFAULT_PRIMARY_MODEL
        )
        self.secondary = secondary_model or os.environ.get(
            "CEREBRAS_SECONDARY_MODEL", DEFAULT_SECONDARY_MODEL
        )

    # ─ Task → model routing ────────────────────────────────────
    def _chain_for_task(self, task: LlmTask) -> list[str]:
        # Long-form benefits from the larger model first; everything else
        # leads with the small fast model and falls back to the larger one
        # only if it errors. Cerebras' 8B is materially faster than 70B
        # and good enough for short, deterministic answers.
        if task == LlmTask.LONG_TEXT:
            return [self.primary, self.secondary]
        return [self.secondary, self.primary]

    # ─ Public entrypoint ───────────────────────────────────────
    def answer(
        self,
        cand: FieldCandidate,
        profile: UserProfile,
    ) -> Optional[LlmAnswer]:
        task = _pick_task(cand)
        prompt = _build_prompt(task, cand, profile)
        for model in self._chain_for_task(task):
            try:
                raw = self._complete(model, prompt, task)
                parsed = _parse_response(raw, task, cand)
                if parsed is not None:
                    return LlmAnswer(
                        value=parsed,
                        confidence=_confidence_for_task(task, cand),
                        model=model,
                        reasoning=raw[:500],
                    )
            except Exception as e:
                log.warning("llm_model_failed", extra={"model": model, "error": str(e)})
                continue
        return None

    # ─ Internals ───────────────────────────────────────────────
    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def _complete(self, model: str, prompt: str, task: LlmTask) -> str:
        max_tokens = 800 if task == LlmTask.LONG_TEXT else 120
        temp = 0.4 if task == LlmTask.LONG_TEXT else 0.1
        resp = self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
            temperature=temp,
        )
        return resp.choices[0].message.content or ""


# ── Backward-compat alias ───────────────────────────────────────
# The class used to be called NimClient. Existing imports across the
# worker have been updated, but this alias keeps any external callers
# (scripts, notebooks, future tests) from breaking on the rename.
NimClient = CerebrasClient


# ─── Prompts ────────────────────────────────────────────────────
SYSTEM_PROMPT = (
    "You are Instaply, an autofill engine for job applications. You produce "
    "precise, truthful answers on behalf of the candidate, using ONLY the "
    "profile and resume evidence provided. Never invent facts not in the "
    "evidence. Never exaggerate experience. Never infer a degree, major, "
    "technical background, employer, or years-of-experience claim unless it "
    "is explicitly supported by the evidence. If the profile lacks the "
    "information needed, "
    "respond with the literal token <<INSUFFICIENT_DATA>>. Always respond in "
    "the exact format the user requests."
)


def _build_prompt(task: LlmTask, cand: FieldCandidate, profile: UserProfile) -> str:
    profile_blob = json.dumps(
        profile.model_dump(
            exclude={
                "resume_parsed_json",
                "resume_text_excerpt",
                "resume_local_path",
                "cover_letter_local_path",
            }
        ),
        indent=2,
        default=str,
    )
    question = cand.label or cand.aria_label or cand.placeholder or cand.name_attr or cand.dom_id
    context = cand.question_context or ""
    base = (
        f"CANDIDATE PROFILE (JSON):\n{profile_blob}\n\n"
        f"QUESTION: {question}\n"
    )
    if profile.resume_parsed_json:
        base += (
            "STRUCTURED RESUME EVIDENCE (JSON):\n"
            f"{json.dumps(profile.resume_parsed_json, indent=2, default=str)[:2500]}\n\n"
        )
    if profile.resume_text_excerpt:
        base += (
            "RAW RESUME TEXT EXCERPT:\n"
            f"{profile.resume_text_excerpt[:2500]}\n\n"
        )
    if context:
        base += f"SURROUNDING CONTEXT: {context}\n"
    if cand.max_length:
        base += f"MAX LENGTH: {cand.max_length} characters\n"

    if task == LlmTask.YES_NO:
        opts = " | ".join(cand.options) if cand.options else "Yes | No"
        return base + (
            f"OPTIONS: {opts}\n"
            f"Respond with ONE option string exactly. No explanation, no punctuation."
        )
    if task == LlmTask.PICK_OPTION:
        opts = "\n".join(f"- {o}" for o in cand.options)
        return base + (
            f"OPTIONS:\n{opts}\n"
            f"Respond with ONE option string exactly as written above. No explanation."
        )
    if task == LlmTask.SHORT_TEXT:
        return base + (
            "Respond with a single concise line of text. "
            "No preamble, no quotes, no markdown. If insufficient data, respond <<INSUFFICIENT_DATA>>."
        )
    # LONG_TEXT
    return base + (
        "Respond with a professional answer in plain text (no markdown). "
        "Keep it under the max length if specified, otherwise 2-4 short paragraphs. "
        "Ground every claim in the profile. If insufficient data, respond <<INSUFFICIENT_DATA>>."
    )


def _parse_response(raw: str, task: LlmTask, cand: FieldCandidate) -> Optional[str]:
    text = (raw or "").strip().strip('"').strip("'")
    if not text or "<<INSUFFICIENT_DATA>>" in text:
        return None
    if task in (LlmTask.PICK_OPTION, LlmTask.YES_NO) and cand.options:
        # Match case-insensitively, return the canonical option
        low = text.lower()
        for opt in cand.options:
            if opt.lower() == low:
                return opt
        for opt in cand.options:
            if opt.lower() in low or low in opt.lower():
                return opt
        return None   # model returned something off-menu; don't guess
    return text


def _confidence_for_task(task: LlmTask, cand: FieldCandidate) -> float:
    # Short deterministic answers are highest confidence; free-form lowest.
    if task == LlmTask.YES_NO:
        return 0.82
    if task == LlmTask.PICK_OPTION:
        return 0.78
    if task == LlmTask.SHORT_TEXT:
        return 0.72
    return 0.68   # long text always gets human review anyway
