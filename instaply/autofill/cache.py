"""Answer cache — the single biggest cost lever.

Every LLM call is expensive (even on free tier we burn latency + quota).
Caching by question_hash × user_id means we pay for an answer ONCE across
a user's entire lifetime.

Actual production schema (verified live):
  answers(id, user_id, question_hash, question_text, answer_text,
          company_slug, times_used, last_used_at, created_at)

Note: the earlier comment here referenced `field_type`, `model`,
`confidence`, and `usage_count` — those columns were planned but never
materialized in 0001_init.sql. `store()` used to write them and would
fail against production. Writes are now trimmed to the real columns.

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


_RAW_NAME_PATTERNS = [
    # Lever EEO fields: eeo[race] → "Race (EEO)", eeo[gender] → "Gender (EEO)"
    (re.compile(r"^eeo\[([a-zA-Z]+)\]$"),
        lambda m: f"{_humanize(m.group(1))} (EEO)"),
    # Lever custom-question cards: cards[uuid][field0] → "Custom question 1"
    (re.compile(r"^cards\[[^\]]+\]\[field(\d+)\]$"),
        lambda m: f"Custom question {int(m.group(1)) + 1}"),
    # Lever surveys: surveysResponses[uuid][responses][field2] → "Survey question 3"
    (re.compile(r"^surveysResponses\[[^\]]+\]\[responses\]\[field(\d+)\]$"),
        lambda m: f"Survey question {int(m.group(1)) + 1}"),
    # lv_radio_<rawname> wrapper used by lever radio dom_ids
    (re.compile(r"^lv_radio_(.+)$"),
        lambda m: m.group(1)),  # let the inner name re-match below
    # Greenhouse anonymous custom-question name attrs: `gh_<hex>` (e.g.
    # gh_b8209158) appear when the GH adapter couldn't find a proper
    # label for a custom screening question. Prettify to a generic
    # "Custom question (Greenhouse)" so the dashboard's cryptic-detection
    # heuristic can then route it to the "Open form" CTA — the user
    # can't safely type into a box labeled `gh_b8209158`.
    (re.compile(r"^gh_[a-f0-9]+$"),
        lambda m: "Custom question (Greenhouse)"),
]


def _humanize(token: str) -> str:
    """`disabilitySignatureDate` → `Disability Signature Date`."""
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", token).replace("_", " ")
    return spaced[:1].upper() + spaced[1:] if spaced else token


def _prettify_raw_name(text: str) -> str:
    """Best-effort: turn a raw form `name` attr into something a tester
    can read. Only fires when the upstream label resolver gave up — we
    never override a real label. Returns the input unchanged if no
    pattern fits.
    """
    if not text:
        return text
    for _ in range(2):  # allow one re-pass for lv_radio_<inner>
        matched = False
        for pat, fmt in _RAW_NAME_PATTERNS:
            m = pat.match(text)
            if m:
                text = fmt(m)
                matched = True
                break
        if not matched:
            return text
    return text


def field_question(cand: FieldCandidate) -> str:
    """Derive the question text we hash on.

    Prefer the visible label; fall back to aria-label, placeholder, or
    name. Raw form `name` attributes (e.g. `eeo[race]`,
    `cards[uuid][field0]`) get prettified into human-readable strings
    so the dashboard's needs_review cards don't show backend gibberish.
    """
    text = (
        cand.label
        or cand.aria_label
        or cand.question_context
        or cand.placeholder
        or cand.name_attr
        or cand.id_attr
        or cand.dom_id
    )
    # Only run the prettifier on the raw-name fallbacks; real labels
    # almost never look like `eeo[race]` and we don't want to mangle them.
    if text and not (cand.label or cand.aria_label or cand.question_context or cand.placeholder):
        return _prettify_raw_name(text)
    return text


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
                # Generic (company_slug=NULL) hits USED to return 0.80
                # here, which sits below EngineConfig.min_cache_confidence
                # (0.85) and caused every generic hit to be rejected by
                # the engine regardless of whether the hash matched.
                # Together with the API/worker hash mismatch, this made
                # the answer vault effectively write-only for
                # generic-scope answers (which is most of them — the
                # /answers/save endpoint does not collect company_slug).
                # Return 0.85 so explicit user-taught answers clear the
                # threshold. Company-specific hits are still preferred
                # because they're checked first (step 1 above).
                confidence=float(r.get("confidence") or 0.85),
                model=r.get("model"),
                source_company_slug=None,
            )
        return None

    def store(self, user_id, question, answer, confidence, model, field_type, company_slug=None):
        """Upsert an answer for future reuse.

        `confidence`, `model`, and `field_type` are accepted to preserve
        the caller contract, but are NOT written — those columns don't
        exist in the production `answers` table. Adding them is a
        separate migration (future work).
        """
        h = question_hash(question)
        self.client.table("answers").upsert(
            {
                "user_id": user_id,
                "question_hash": h,
                "question_text": question[:2000],     # guard against bloat
                "answer_text": answer,
                "company_slug": company_slug,
            },
            on_conflict="user_id,question_hash,company_slug",
        ).execute()

    def _bump_usage(self, answer_id: str) -> None:
        # Fire-and-forget; failure is non-fatal. Uses `times_used` on the
        # answers table (schema-accurate name) if the RPC isn't present.
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
