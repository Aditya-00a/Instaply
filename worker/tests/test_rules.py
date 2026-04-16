"""Rules + engine smoke test.

Runs without network — uses MemoryAnswerCache and no LLM.
Proves the deterministic path: a plausible Greenhouse-ish form produces
correct decisions for every rule-covered field.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running as `python -m pytest worker/tests/` from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from worker.autofill import FieldCandidate, UserProfile, resolve_field
from worker.autofill.cache import MemoryAnswerCache
from worker.autofill.models import DecisionSource, FieldType


PROFILE = UserProfile(
    user_id="00000000-0000-0000-0000-000000000001",
    first_name="Aditya",
    last_name="Sakhale",
    full_name="Aditya Sakhale",
    email="aditya@example.com",
    phone_e164="+12125551234",
    phone_national="212-555-1234",
    linkedin_url="https://linkedin.com/in/aditya",
    github_url="https://github.com/aditya",
    portfolio_url="https://asion.ai",
    city="New York",
    state="NY",
    country="United States",
    postal_code="10003",
    work_auth_status="opt",
    needs_sponsorship=True,
    current_company="Ravendise",
    current_title="Founder",
    years_experience=2,
    school="New York University",
    degree="Master's",
    major="Computer Science",
    graduation_year=2026,
    willing_to_relocate=True,
    salary_expectation_usd=120000,
    resume_local_path="/tmp/resume.pdf",
)


def _cand(**kw) -> FieldCandidate:
    kw.setdefault("dom_id", "f_" + (kw.get("name_attr") or kw.get("label", "x")).replace(" ", "_"))
    kw.setdefault("field_type", FieldType.TEXT)
    return FieldCandidate(**kw)


# ─── Each test asserts source=RULE and the expected value ─────

def test_first_name():
    d = resolve_field(_cand(label="First Name", name_attr="first_name"), PROFILE)
    assert d.source == DecisionSource.RULE
    assert d.value == "Aditya"


def test_last_name():
    d = resolve_field(_cand(label="Last Name", name_attr="last_name"), PROFILE)
    assert d.source == DecisionSource.RULE
    assert d.value == "Sakhale"


def test_full_name():
    d = resolve_field(_cand(label="Full Name", name_attr="name"), PROFILE)
    assert d.source == DecisionSource.RULE
    assert d.value == "Aditya Sakhale"


def test_email():
    d = resolve_field(_cand(label="Email", field_type=FieldType.EMAIL), PROFILE)
    assert d.source == DecisionSource.RULE
    assert d.value == "aditya@example.com"


def test_phone():
    d = resolve_field(_cand(label="Phone Number", field_type=FieldType.TEL), PROFILE)
    assert d.source == DecisionSource.RULE
    assert d.value == "+12125551234"


def test_linkedin():
    d = resolve_field(_cand(label="LinkedIn Profile", field_type=FieldType.URL), PROFILE)
    assert d.source == DecisionSource.RULE
    assert "linkedin.com" in d.value


def test_github():
    d = resolve_field(_cand(label="GitHub", field_type=FieldType.URL), PROFILE)
    assert d.source == DecisionSource.RULE
    assert "github.com" in d.value


def test_portfolio_prefers_portfolio_over_website():
    d = resolve_field(_cand(label="Portfolio URL", field_type=FieldType.URL), PROFILE)
    assert d.value == "https://asion.ai"


def test_city():
    d = resolve_field(_cand(label="City"), PROFILE)
    assert d.value == "New York"


def test_state():
    d = resolve_field(_cand(label="State"), PROFILE)
    assert d.value == "NY"


def test_school():
    d = resolve_field(_cand(label="University"), PROFILE)
    assert d.value == "New York University"


def test_work_authorization_yes():
    d = resolve_field(
        _cand(
            label="Are you legally authorized to work in the US?",
            field_type=FieldType.SELECT,
            options=["Yes", "No"],
        ),
        PROFILE,
    )
    assert d.source == DecisionSource.RULE
    assert d.value == "Yes"
    assert d.required_review is True  # always review work-auth


def test_sponsorship_yes():
    d = resolve_field(
        _cand(
            label="Will you now or in the future require visa sponsorship?",
            field_type=FieldType.SELECT,
            options=["Yes", "No"],
        ),
        PROFILE,
    )
    assert d.source == DecisionSource.RULE
    assert d.value == "Yes"
    assert d.required_review is True


def test_resume_upload():
    d = resolve_field(
        _cand(label="Resume", field_type=FieldType.FILE),
        PROFILE,
    )
    assert d.source == DecisionSource.RULE
    assert d.value == "/tmp/resume.pdf"


def test_unknown_field_with_no_cache_no_llm_becomes_skip_or_review():
    # Required unknown = REVIEW, optional unknown = SKIP
    required = resolve_field(
        _cand(label="Why do you want to work here?", field_type=FieldType.TEXTAREA, required=True),
        PROFILE,
        cache=MemoryAnswerCache(),
    )
    assert required.source == DecisionSource.REVIEW

    optional = resolve_field(
        _cand(label="Referral source", field_type=FieldType.TEXT, required=False),
        PROFILE,
        cache=MemoryAnswerCache(),
    )
    assert optional.source == DecisionSource.SKIP


def test_cache_hit_reuses_answer():
    cache = MemoryAnswerCache()
    cache.store(
        user_id=PROFILE.user_id,
        question="Why do you want to work here?",
        answer="I admire the team's work on X and want to contribute to Y.",
        confidence=0.9,
        model="test",
        field_type="textarea",
    )
    d = resolve_field(
        _cand(label="Why do you want to work here?", field_type=FieldType.TEXTAREA, required=True),
        PROFILE,
        cache=cache,
    )
    assert d.source == DecisionSource.CACHE
    assert "admire" in d.value
