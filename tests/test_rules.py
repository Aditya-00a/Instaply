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
    first_name="Jordan",
    last_name="Lee",
    full_name="Jordan Lee",
    email="jordan.lee@example.com",
    phone_e164="+12125551234",
    phone_national="212-555-1234",
    linkedin_url="https://linkedin.com/in/jordan-lee",
    github_url="https://github.com/jordanlee",
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
    assert d.value == "Jordan"


def test_last_name():
    d = resolve_field(_cand(label="Last Name", name_attr="last_name"), PROFILE)
    assert d.source == DecisionSource.RULE
    assert d.value == "Lee"


def test_full_name():
    d = resolve_field(_cand(label="Full Name", name_attr="name"), PROFILE)
    assert d.source == DecisionSource.RULE
    assert d.value == "Jordan Lee"


def test_email():
    d = resolve_field(_cand(label="Email", field_type=FieldType.EMAIL), PROFILE)
    assert d.source == DecisionSource.RULE
    assert d.value == "jordan.lee@example.com"


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


def test_sponsorship_explicit_does_not_escalate():
    """needs_sponsorship is explicitly set in the profile → auto-answer
    without review (the dynamic resolver introduced 2026-04-18 only
    escalates when the profile is ambiguous / None)."""

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
    # Explicit needs_sponsorship=True in the profile — engine auto-answers
    # without holding the form for review.
    assert d.required_review is False


def test_sponsorship_ambiguous_does_escalate():
    """Profile.needs_sponsorship is None → escalate. Defaulting to a
    silent No could mis-represent an OPT/H-1B applicant who simply
    didn't fill the field during onboarding."""
    ambiguous = PROFILE.model_copy(update={"needs_sponsorship": None})
    d = resolve_field(
        _cand(
            label="Will you now or in the future require visa sponsorship?",
            field_type=FieldType.SELECT,
            options=["Yes", "No"],
        ),
        ambiguous,
    )
    # Either way the rule still produces a value (or None falls through),
    # but if it produces a value it MUST be flagged for review.
    # Two acceptable outcomes:
    #   1. Rule returned a value (auto-yes/no) → MUST be flagged for review
    #      because the profile didn't actually express a preference.
    #   2. Resolver returned None → engine falls through. For an optional
    #      field that means SKIP; for a required field that would be REVIEW.
    if d.source == DecisionSource.RULE:
        assert d.required_review is True
    else:
        assert d.source in (DecisionSource.REVIEW, DecisionSource.SKIP)


def test_work_auth_us_citizen_does_not_escalate():
    """work_auth_status='us_citizen' is unambiguous → auto-answer Yes
    without review."""
    citizen = PROFILE.model_copy(update={"work_auth_status": "us_citizen"})
    d = resolve_field(
        _cand(
            label="Are you legally authorized to work in the United States?",
            field_type=FieldType.SELECT,
            options=["Yes", "No"],
        ),
        citizen,
    )
    assert d.source == DecisionSource.RULE
    assert d.value == "Yes"
    assert d.required_review is False


def test_pronouns_unset_does_not_answer():
    """Profile.pronouns is None → resolver returns None → engine
    escalates. CRITICAL: pronouns must NEVER be inferred from gender."""
    no_pronouns = PROFILE.model_copy(update={"pronouns": None, "gender": "female"})
    d = resolve_field(
        _cand(label="What are your pronouns?", field_type=FieldType.TEXT),
        no_pronouns,
    )
    # No rule value → engine fell through. Acceptable: REVIEW (required) or SKIP.
    assert d.value is None or d.source != DecisionSource.RULE
    assert d.source in (DecisionSource.REVIEW, DecisionSource.SKIP)


def test_pronouns_explicit_text_field():
    explicit = PROFILE.model_copy(update={"pronouns": "she/her"})
    d = resolve_field(
        _cand(label="Pronouns", field_type=FieldType.TEXT),
        explicit,
    )
    assert d.source == DecisionSource.RULE
    assert d.value == "she/her"
    assert d.required_review is False


def test_pronouns_multicheckbox_only_ticks_matching_option():
    """Lever-style layout: each pronoun option is its own checkbox.
    User has she/her → only the She/her checkbox returns Yes; everything
    else returns No. No more LLM hallucinating wrong pronouns."""
    explicit = PROFILE.model_copy(update={"pronouns": "she/her"})

    d_match = resolve_field(
        _cand(label="She/her", field_type=FieldType.CHECKBOX),
        explicit,
    )
    assert d_match.source == DecisionSource.RULE
    assert d_match.value == "Yes"

    d_other = resolve_field(
        _cand(label="He/him", field_type=FieldType.CHECKBOX),
        explicit,
    )
    assert d_other.source == DecisionSource.RULE
    assert d_other.value == "No"

    d_third = resolve_field(
        _cand(label="They/them", field_type=FieldType.CHECKBOX),
        explicit,
    )
    assert d_third.source == DecisionSource.RULE
    assert d_third.value == "No"


def test_pronouns_never_inferred_from_gender():
    """Strict guarantee: a profile with gender set but pronouns unset
    must NOT auto-answer pronouns questions, even though it would be
    'reasonable' to guess. This is the bug we observed in production."""
    for g in ("female", "male", "non_binary", "other"):
        gendered = PROFILE.model_copy(update={"pronouns": None, "gender": g})
        d = resolve_field(
            _cand(label="She/her", field_type=FieldType.CHECKBOX),
            gendered,
        )
        # Either no rule value at all, or fall to REVIEW/SKIP — never RULE+value
        if d.source == DecisionSource.RULE:
            assert d.value is None, f"gender={g} produced a pronoun guess: {d.value!r}"
        else:
            assert d.source in (DecisionSource.REVIEW, DecisionSource.SKIP)


def test_pronouns_custom_option_checkbox_id_only_match_resolves_no():
    """Lever renders the 'Custom' pronouns option as a bare checkbox
    with id='customPronounsOption' and no proper <label>. The parser's
    only signal is the id_attr. Before 2026-04-18 the rule confidence
    of 0.90 produced an id-match score of 0.90 * 0.88 = 0.792 — JUST
    under min_rule_confidence (0.80) — so the candidate fell through to
    the LLM, which hallucinated a paragraph into the field. The rule
    now sits at 0.95 (id-match score 0.836 >= 0.80) and resolves the
    Custom checkbox to 'No' for a user who picked a standard pronoun.
    """
    he_him = PROFILE.model_copy(update={"pronouns": "he/him"})
    d = resolve_field(
        _cand(
            label="Custom",
            field_type=FieldType.CHECKBOX,
            dom_id="customPronounsOption",
            id_attr="customPronounsOption",
        ),
        he_him,
    )
    assert d.source == DecisionSource.RULE, f"expected RULE, got {d.source}"
    assert d.value == "No"
    assert d.required_review is False


def test_pronouns_select_picks_matching_option():
    explicit = PROFILE.model_copy(update={"pronouns": "they/them"})
    d = resolve_field(
        _cand(
            label="What are your pronouns?",
            field_type=FieldType.SELECT,
            options=["She/her", "He/him", "They/them", "Prefer not to say"],
        ),
        explicit,
    )
    assert d.source == DecisionSource.RULE
    assert d.value == "They/them"  # canonical option text returned, not lower-case
    assert d.required_review is False


def test_age_18_or_older_auto_answers_yes():
    d = resolve_field(
        _cand(
            label="Are you at least 18 years of age?",
            field_type=FieldType.RADIO,
            options=["Yes", "No"],
        ),
        PROFILE,
    )
    assert d.source == DecisionSource.RULE
    assert d.value == "Yes"
    assert d.required_review is False


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
