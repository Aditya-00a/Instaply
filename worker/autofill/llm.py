"""NIM fallback — when rules and cache both miss.

Per-task model routing with a fallback chain so one model being down
doesn't halt an application run.

Routing:
  - short_text    (names, single-line answers)          -> secondary (Llama 3.3 70B)
  - long_text     (cover letter, 'why this role')       -> primary   (Nemotron Super 49B)
  - pick_option   (dropdowns, radios)                   -> nano      (fast; TODO expose)
  - yes_no        (binary radios)                       -> nano
  - ranking       (fit score; not used in autofill)     -> reasoning (Kimi K2)

If the assigned model 429s or errors, we walk down the chain:
  primary -> secondary -> reasoning -> (give up, return SKIP)
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


class NimClient:
    """Thin wrapper over OpenAI-compatible NIM endpoint with fallback chain."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        primary_model: Optional[str] = None,
        secondary_model: Optional[str] = None,
        reasoning_model: Optional[str] = None,
    ):
        api_key = api_key or os.environ.get("NVIDIA_NIM_API_KEY")
        base_url = base_url or os.environ.get("NVIDIA_NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")
        if not api_key:
            raise RuntimeError("NVIDIA_NIM_API_KEY not set")
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.primary = primary_model or os.environ.get(
            "NVIDIA_NIM_PRIMARY_MODEL", "nvidia/llama-3.3-nemotron-super-49b-v1.5"
        )
        self.secondary = secondary_model or os.environ.get(
            "NVIDIA_NIM_SECONDARY_MODEL", "meta/llama-3.3-70b-instruct"
        )
        self.reasoning = reasoning_model or os.environ.get(
            "NVIDIA_NIM_REASONING_MODEL", "moonshotai/kimi-k2-thinking"
        )

    # ─ Task → model routing ────────────────────────────────────
    def _chain_for_task(self, task: LlmTask) -> list[str]:
        if task == LlmTask.LONG_TEXT:
            return [self.primary, self.secondary, self.reasoning]
        if task == LlmTask.SHORT_TEXT:
            return [self.secondary, self.primary, self.reasoning]
        # PICK_OPTION and YES_NO — fast tasks; secondary is fine
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
                log.warning("nim_model_failed", extra={"model": model, "error": str(e)})
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


# ─── Prompts ────────────────────────────────────────────────────
SYSTEM_PROMPT = (
    "You are Instaply, an autofill engine for job applications. You produce "
    "precise, truthful answers on behalf of the candidate, using ONLY the "
    "profile data provided. Never invent facts not in the profile. Never "
    "exaggerate experience. If the profile lacks the information needed, "
    "respond with the literal token <<INSUFFICIENT_DATA>>. Always respond in "
    "the exact format the user requests."
)


def _build_prompt(task: LlmTask, cand: FieldCandidate, profile: UserProfile) -> str:
    profile_blob = json.dumps(
        profile.model_dump(exclude={"resume_parsed_json", "resume_local_path", "cover_letter_local_path"}),
        indent=2,
        default=str,
    )
    question = cand.label or cand.aria_label or cand.placeholder or cand.name_attr or cand.dom_id
    context = cand.question_context or ""
    base = (
        f"CANDIDATE PROFILE (JSON):\n{profile_blob}\n\n"
        f"QUESTION: {question}\n"
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
