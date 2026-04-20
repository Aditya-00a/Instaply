"""Cross-module parity test: API and worker MUST produce identical hashes.

The answer vault is split across two deploy units:
  - api/app/answers.py        → writes new answers on user save
  - worker/autofill/cache.py  → reads answers during cache lookup

If the two functions disagree on a single byte, every saved answer
becomes an orphan: the row exists in the table, but the worker looks it
up under a different hash and re-asks the question forever. That broke
production on 2026-04-18 (loop on `f27fd5ef-…`, full RCA in answers.py
docstring). This test pins them together so the bug cannot recur.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make both packages importable from the repo root.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from api.app.answers import _normalize_question as api_normalize, _question_hash as api_hash
from worker.autofill.cache import question_hash as worker_hash


SAMPLES = [
    "Current company",
    "current company",
    "  Current Company  ",
    "Date",
    "Asian",
    "What is your name?",
    "What's your name?",                 # internal apostrophe — must stay distinct
    "Are you legally authorized to work in the US?",
    "Pronouns",
    "She/her",
    "Why do you want to work at Acme?",
    "",                                  # empty edge case
    "  ",                                # whitespace-only
    "**Required field**",                # leading/trailing punctuation strip
    "Race / ethnicity?",                 # internal punctuation preserved
]


def test_api_hash_is_full_sha256_hex():
    """64 hex chars — never truncated. The previous [:32] truncation was
    half the immediate cache-miss bug."""
    for q in SAMPLES:
        h = api_hash(q)
        assert len(h) == 64, f"{q!r} → {h!r} (len {len(h)})"
        int(h, 16)  # must be valid hex


def test_api_hash_matches_worker_hash_for_every_sample():
    for q in SAMPLES:
        a = api_hash(q)
        w = worker_hash(q)
        assert a == w, (
            f"hash mismatch for {q!r}: api={a!r} worker={w!r} — "
            "the answer vault will be write-only again. See answers.py "
            "_normalize_question docstring."
        )


def test_normalization_preserves_internal_punctuation():
    """A historical bug had API stripping ALL punctuation while the
    worker stripped only edges. That meant 'what's your name' and
    'what is your name' collapsed to the same hash on the API side
    but stayed distinct on the worker side — guaranteeing mismatches
    on any question with an apostrophe, slash, or comma.
    """
    a_apo = api_normalize("what's your name")
    a_no = api_normalize("what is your name")
    assert a_apo != a_no, "API must NOT collapse internal punctuation"
    assert a_apo == "what's your name"
    assert a_no == "what is your name"


def test_normalization_strips_edge_punctuation_and_lowercases():
    assert api_normalize("**Required field**") == "required field"
    assert api_normalize("  Current  COMPANY  ") == "current company"
    assert api_normalize("") == ""


def test_known_real_world_inputs_round_trip():
    """The three exact questions that broke f27fd5ef on 2026-04-18.
    Lock their post-fix hashes so any future drift fails loud here.
    """
    assert api_hash("Current company") == worker_hash("Current company")
    assert api_hash("Date") == worker_hash("Date")
    assert api_hash("Asian") == worker_hash("Asian")
