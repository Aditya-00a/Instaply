"""The autofill decision loop.

One function: resolve_field(candidate, profile, cache, llm, config) -> FieldDecision

Order of operations:
  1. RULES       -> if a rule matches AND resolves to a value, use it.
  2. CACHE       -> if this user answered this question before, reuse it.
  3. LLM         -> NIM fallback, writes back to cache on success.
  4. SKIP/REVIEW -> no good answer; flag for human or leave blank if optional.

Anywhere a rule is marked `requires_review=True`, the decision is still
filled but `required_review` is True — the worker will hold the form for
user approval before hitting submit.
"""
from __future__ import annotations

import logging
from typing import Optional

from .cache import AnswerCache, field_question
from .llm import NimClient
from .models import (
    DecisionSource,
    EngineConfig,
    FieldCandidate,
    FieldDecision,
    UserProfile,
)
from .rules import best_rule_match

log = logging.getLogger(__name__)


def resolve_field(
    cand: FieldCandidate,
    profile: UserProfile,
    cache: Optional[AnswerCache] = None,
    llm: Optional[NimClient] = None,
    config: Optional[EngineConfig] = None,
) -> FieldDecision:
    """Single field -> single decision. No side effects beyond cache writes."""
    config = config or EngineConfig()

    # ── Stage 1: rules ──────────────────────────────────────────
    rule, score = best_rule_match(cand)
    if rule and score >= config.min_rule_confidence:
        value = rule.resolver(profile, cand)
        if _non_empty(value):
            return FieldDecision(
                dom_id=cand.dom_id,
                value=value,
                source=DecisionSource.RULE,
                confidence=score,
                rule_id=rule.id,
                reasoning=f"rule match on '{rule.id}' (score {score:.2f})",
                required_review=rule.requires_review,
            )

    # ── Stage 2: cache ──────────────────────────────────────────
    question = field_question(cand)
    if cache is not None and question:
        hit = cache.lookup(profile.user_id, question, cand.company_slug)
        if hit and hit.confidence >= config.min_cache_confidence:
            return FieldDecision(
                dom_id=cand.dom_id,
                value=hit.answer,
                source=DecisionSource.CACHE,
                confidence=hit.confidence,
                model=hit.model,
                reasoning=f"cache hit (company_slug={hit.source_company_slug})",
                required_review=False,
            )

    # ── Stage 3: LLM ────────────────────────────────────────────
    if llm is not None and question:
        try:
            ans = llm.answer(cand, profile)
        except Exception as e:
            log.exception("llm_failed", extra={"dom_id": cand.dom_id, "err": str(e)})
            ans = None
        if ans and ans.confidence >= config.min_llm_confidence and _non_empty(ans.value):
            # Write back to cache so we never pay for this answer again.
            if cache is not None:
                try:
                    cache.store(
                        user_id=profile.user_id,
                        question=question,
                        answer=str(ans.value),
                        confidence=ans.confidence,
                        model=ans.model,
                        field_type=cand.field_type.value,
                        company_slug=cand.company_slug,
                    )
                except Exception:
                    log.exception("cache_store_failed")
            return FieldDecision(
                dom_id=cand.dom_id,
                value=ans.value,
                source=DecisionSource.LLM,
                confidence=ans.confidence,
                model=ans.model,
                reasoning=f"llm fallback ({ans.model})",
                required_review=True,   # LLM-generated always gets reviewed on first use
            )

    # ── Stage 4: skip or review ─────────────────────────────────
    # Required fields without an answer block the submit — flag REVIEW.
    # Optional fields are safely skipped.
    source = DecisionSource.REVIEW if cand.required else DecisionSource.SKIP
    return FieldDecision(
        dom_id=cand.dom_id,
        value=None,
        source=source,
        confidence=0.0,
        reasoning="no rule/cache/llm answer available",
        required_review=cand.required,
    )


def _non_empty(v) -> bool:
    if v is None:
        return False
    if isinstance(v, str) and not v.strip():
        return False
    if isinstance(v, (list, tuple, set, dict)) and len(v) == 0:
        return False
    return True
