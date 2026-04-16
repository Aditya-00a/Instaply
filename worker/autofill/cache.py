"""Answer cache — the single biggest cost lever.

Every LLM call is expensive (even on free tier we burn latency + quota).
Caching by question_hash × user_id means we pay for an answer ONCE across
a user's entire lifetime.

Schema (from 0001_init.sql):
  answers(id, user_id, question_hash, question_text, answer_text,
          field_type, company_slug, model, confidence, created_at, usage_count)

  unique(user_id, question_hash, company_slug)
  question_hash = sha256(normalized_question_text)

Lookup order:
  1. user_id × question_hash × company_slug  (company-specific answer)
  2. user_id × question_hash × NULL          (generic answer, any company)
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Optional, Protocol

from .models import FieldCandidate


def question_hash(text: str) -> str:
    """Normalise a question string to a stable hash.

    Lowercases, collapses whitespace, strips punctuation edges. Done this way
    so 'Why do you want to work at Acme? ' and 'why do you want to work at acme'
    hash the same — the answer travels across companies.
    """
    s = text.lower().strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"^[\W_]+|[\W_]+$", "", s)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def field_question(cand: FieldCandidate) -> str:
    """Derive the question text we hash on.

    Prefer the visible label; fall back to aria-label, placeholder, or name.
    """
    return (
        cand.label
        or cand.aria_label
        or cand.question_context
        or cand.placeholder
        or cand.name_attr
        or cand.id_attr
        or cand.dom_id
    )


@dataclass
class CachedAnswer:
    answer: str
    confidence: float
    model: Optional[str]
    source_company_slug: Optional[str]   # None = generic


class AnswerCache(Protocol):
    """Abstract — implemented over Supabase in cloud, SQLite in desktop."""

    def lookup(
        self,
        user_id: str,
        question: str,
        company_slug: Optional[str],
    ) -> Optional[CachedAnswer]: ...

    def store(
        self,
        user_id: str,
        question: str,
        answer: str,
        confidence: float,
        model: str,
        field_type: str,
        company_slug: Optional[str],
    ) -> None: ...


# ─── Supabase-backed implementation ──────────────────────────────
class SupabaseAnswerCache:
    """Production cache. Passed a supabase-py client at construct time."""

    def __init__(self, client):
        self.client = client

    def lookup(self, user_id, question, company_slug=None):
        h = question_hash(question)
        # 1. Company-specific
        if company_slug:
            resp = (
                self.client.table("answers")
                .select("*")
                .eq("user_id", user_id)
                .eq("question_hash", h)
                .eq("company_slug", company_slug)
                .limit(1)
                .execute()
            )
            if resp.data:
                r = resp.data[0]
                self._bump_usage(r["id"])
                return CachedAnswer(
                    answer=r["answer_text"],
                    confidence=float(r.get("confidence") or 0.85),
                    model=r.get("model"),
                    source_company_slug=r.get("company_slug"),
                )
        # 2. Generic (company_slug NULL)
        resp = (
            self.client.table("answers")
            .select("*")
            .eq("user_id", user_id)
            .eq("question_hash", h)
            .is_("company_slug", "null")
            .limit(1)
            .execute()
        )
        if resp.data:
            r = resp.data[0]
            self._bump_usage(r["id"])
            return CachedAnswer(
                answer=r["answer_text"],
                confidence=float(r.get("confidence") or 0.80),  # slightly lower than company-specific
                model=r.get("model"),
                source_company_slug=None,
            )
        return None

    def store(self, user_id, question, answer, confidence, model, field_type, company_slug=None):
        h = question_hash(question)
        self.client.table("answers").upsert(
            {
                "user_id": user_id,
                "question_hash": h,
                "question_text": question[:2000],     # guard against bloat
                "answer_text": answer,
                "field_type": field_type,
                "company_slug": company_slug,
                "model": model,
                "confidence": confidence,
            },
            on_conflict="user_id,question_hash,company_slug",
        ).execute()

    def _bump_usage(self, answer_id: str) -> None:
        # Fire-and-forget; failure is non-fatal.
        try:
            self.client.rpc("bump_answer_usage", {"p_answer_id": answer_id}).execute()
        except Exception:
            pass


# ─── In-memory cache (for tests + first-application runs) ───────
class MemoryAnswerCache:
    def __init__(self) -> None:
        self._store: dict[tuple[str, str, Optional[str]], CachedAnswer] = {}

    def lookup(self, user_id, question, company_slug=None):
        h = question_hash(question)
        if company_slug:
            hit = self._store.get((user_id, h, company_slug))
            if hit:
                return hit
        return self._store.get((user_id, h, None))

    def store(self, user_id, question, answer, confidence, model, field_type, company_slug=None):
        h = question_hash(question)
        self._store[(user_id, h, company_slug)] = CachedAnswer(
            answer=answer, confidence=confidence, model=model, source_company_slug=company_slug,
        )
