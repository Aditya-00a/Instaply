"""Regression: generic (company_slug=NULL) cache hits must clear the
EngineConfig.min_cache_confidence threshold.

Before 2026-04-18 the SupabaseAnswerCache hard-coded confidence=0.80
on the generic-scope branch. EngineConfig.min_cache_confidence is 0.85.
Result: every generic answer got found, then immediately rejected, and
times_used stayed 0 forever. Combined with an API/worker hash mismatch
(see api/tests/test_answers_hash_parity.py), this made Save & Retry a
no-op — the f27fd5ef incident.

These tests use a fake supabase client so we don't need network/DB.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from worker.autofill.cache import SupabaseAnswerCache, question_hash
from worker.autofill.models import EngineConfig


class _FakeBuilder:
    def __init__(self, rows):
        self._rows = rows
        self._filters = {}

    def select(self, *_a, **_k): return self
    def eq(self, k, v): self._filters[k] = v; return self
    def is_(self, k, v): self._filters[k] = ("IS", v); return self
    def limit(self, _n): return self

    def execute(self):
        # Return only rows that match all .eq filters (and IS NULL filter).
        out = []
        for r in self._rows:
            ok = True
            for k, v in self._filters.items():
                if isinstance(v, tuple) and v[0] == "IS":
                    # Treat IS NULL match as r[k] is None
                    if r.get(k) is not None:
                        ok = False; break
                elif r.get(k) != v:
                    ok = False; break
            if ok:
                out.append(r)
        return type("R", (), {"data": out})()


class _FakeClient:
    def __init__(self, rows):
        self._rows = rows
        self.bumped: list[str] = []

    def table(self, _name):
        return _FakeBuilder(self._rows)

    def rpc(self, name, args):
        if name == "bump_answer_usage":
            self.bumped.append(args["p_answer_id"])
        return type("R", (), {"execute": lambda s=None: type("R2", (), {"data": []})()})()


def test_generic_cache_hit_clears_engine_threshold():
    """A generic-scope answer (company_slug=NULL) MUST be returned with
    a confidence at or above the engine's min_cache_confidence.
    Otherwise the engine throws it away and the user sees the same
    needs_review question again."""
    user_id = "u-1"
    q = "Current company"
    rows = [{
        "id": "ans-1",
        "user_id": user_id,
        "question_hash": question_hash(q),
        "question_text": q,
        "answer_text": "Ravendise",
        "company_slug": None,
        "times_used": 0,
    }]
    cache = SupabaseAnswerCache(_FakeClient(rows))
    hit = cache.lookup(user_id=user_id, question=q, company_slug="any-company")
    assert hit is not None, "row should be found via generic-fallback path"
    assert hit.answer == "Ravendise"
    assert hit.confidence >= EngineConfig().min_cache_confidence, (
        f"generic hit confidence {hit.confidence} < min_cache_confidence "
        f"{EngineConfig().min_cache_confidence} — engine will reject it "
        "and the user gets stuck in a needs_review loop."
    )


def test_company_specific_hit_still_preferred_over_generic():
    """When both a company-specific and a generic row exist, the
    company-specific one must win (it's checked first, before generic)."""
    user_id = "u-1"
    q = "Why do you want to work here?"
    rows = [
        {
            "id": "specific",
            "user_id": user_id,
            "question_hash": question_hash(q),
            "question_text": q,
            "answer_text": "Because Acme",
            "company_slug": "acme",
            "times_used": 0,
        },
        {
            "id": "generic",
            "user_id": user_id,
            "question_hash": question_hash(q),
            "question_text": q,
            "answer_text": "Generic boilerplate",
            "company_slug": None,
            "times_used": 0,
        },
    ]
    cache = SupabaseAnswerCache(_FakeClient(rows))
    hit = cache.lookup(user_id=user_id, question=q, company_slug="acme")
    assert hit is not None
    assert hit.answer == "Because Acme"


def test_lookup_miss_returns_none():
    cache = SupabaseAnswerCache(_FakeClient([]))
    hit = cache.lookup(user_id="u-1", question="anything", company_slug=None)
    assert hit is None
