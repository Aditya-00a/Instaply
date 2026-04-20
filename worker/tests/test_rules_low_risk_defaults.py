"""Regression tests for the 2026-04-18 candidate-favorable-defaults
rule family.

For factual low-risk yes/no questions about prior relationship, account
status, or referrals, the rules engine MUST default to "No" silently
(no needs_review escalation) so the form can submit. The first real
exposure was Wealthfront's "Are you currently a Wealthfront client?"
checkbox blocking submit on `08053cf9` — a question that is almost
always No for a first-time applicant.

CRITICAL safety envelope: this family must NEVER fire on legal,
work-authorization, sponsorship, EEO, criminal, salary, disability, or
veteran-status questions. Those have their own dedicated rules with
review escalation built in. The negative tests at the bottom of this
file lock that envelope in place.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from worker.autofill import FieldCandidate, resolve_field
from worker.autofill.models import DecisionSource, FieldType
from .test_rules import PROFILE  # reuse the canonical profile fixture


def _cand(**kw) -> FieldCandidate:
    kw.setdefault("dom_id", "f_" + (kw.get("name_attr") or kw.get("label", "x")).replace(" ", "_"))
    kw.setdefault("field_type", FieldType.SELECT)
    kw.setdefault("options", ["Yes", "No"])
    return FieldCandidate(**kw)


# ─── current_customer_or_client_no ──────────────────────────────
def test_current_wealthfront_client_auto_no():
    """The exact question that blocked 08053cf9."""
    d = resolve_field(_cand(label="Are you currently a Wealthfront client?"), PROFILE)
    assert d.source == DecisionSource.RULE
    assert d.value == "No"
    assert d.required_review is False


def test_current_customer_phrasings():
    for label in [
        "Are you a current customer?",
        "Are you currently a user of our product?",
        "Are you a member?",
        "Are you currently a subscriber?",
        "Do you have an account with us?",
        "Are you an account holder?",
    ]:
        d = resolve_field(_cand(label=label), PROFILE)
        assert d.source == DecisionSource.RULE, f"missed: {label!r}"
        assert d.value == "No"
        assert d.required_review is False


# ─── referred_by_employee_no ────────────────────────────────────
def test_referred_by_employee_auto_no():
    for label in [
        "Were you referred by an employee?",
        "Are you referred by a current employee?",
        "Employee Referral?",
        "Do you have an employee referral?",
    ]:
        d = resolve_field(_cand(label=label), PROFILE)
        assert d.source == DecisionSource.RULE, f"missed: {label!r}"
        assert d.value == "No"
        assert d.required_review is False


# ─── current_employee_here_no ────────────────────────────────────
def test_current_employee_here_auto_no():
    for label in [
        "Are you a current employee?",
        "Are you currently a current employee?",
        "Are you currently working here?",
        "Are you currently employed with us?",
    ]:
        d = resolve_field(_cand(label=label), PROFILE)
        assert d.source == DecisionSource.RULE, f"missed: {label!r}"
        assert d.value == "No"
        assert d.required_review is False


# ─── previously_employed_here (now no-review) ────────────────────
def test_previously_employed_here_no_longer_escalates():
    """Pre-2026-04-18 this rule auto-answered No but still flagged
    requires_review=True. The candidate-favorable-defaults spec drops
    the review flag — the answer is silent now."""
    d = resolve_field(
        _cand(label="Have you previously been employed by this company?"),
        PROFILE,
    )
    assert d.source == DecisionSource.RULE
    assert d.value == "No"
    assert d.required_review is False


# ─── SAFETY ENVELOPE: must NOT match the auto-No family ─────────
def test_work_authorization_does_not_get_silent_no():
    """Auto-No on work auth would mark a US-citizen applicant as
    unauthorized — disastrous. The work_authorization rule must win."""
    d = resolve_field(
        _cand(label="Are you legally authorized to work in the US?"),
        PROFILE,
    )
    assert d.source == DecisionSource.RULE
    # work_authorization rule fires; the value depends on profile
    # (PROFILE has work_auth_status='opt' → authorized=True). The
    # critical assertion is rule_id, NOT the auto-No value.
    assert d.rule_id in ("work_authorization", "work_auth_country_specific"), (
        f"expected a work-auth rule to win, got {d.rule_id!r} — "
        "the candidate-favorable defaults must NEVER match work auth."
    )


def test_sponsorship_does_not_get_silent_no():
    """Same envelope check for sponsorship questions."""
    d = resolve_field(
        _cand(label="Will you now or in the future require visa sponsorship?"),
        PROFILE,
    )
    assert d.source == DecisionSource.RULE
    assert d.rule_id == "sponsorship", (
        f"expected sponsorship rule to win, got {d.rule_id!r}"
    )


def test_disability_question_does_not_get_silent_no():
    """Disability self-id is a regulated EEO field. The auto-No family
    must never touch it."""
    d = resolve_field(
        _cand(
            label="Do you have a disability?",
            options=["Yes", "No", "Prefer not to say"],
        ),
        PROFILE,
    )
    # Either disability_status rule fires or it falls through to
    # cache/LLM. What it MUST NOT do is hit any of the new
    # *_no rules and silently return "No" without review.
    assert d.rule_id not in (
        "current_customer_or_client_no",
        "referred_by_employee_no",
        "current_employee_here_no",
        "previously_employed_here",
    ), f"auto-No family wrongly matched a disability question: rule_id={d.rule_id!r}"


def test_veteran_question_does_not_get_silent_no():
    d = resolve_field(
        _cand(label="Are you a protected veteran?", options=["Yes", "No"]),
        PROFILE,
    )
    assert d.rule_id not in (
        "current_customer_or_client_no",
        "referred_by_employee_no",
        "current_employee_here_no",
        "previously_employed_here",
    )


def test_salary_expectation_does_not_get_silent_no():
    d = resolve_field(
        _cand(label="What is your salary expectation?", field_type=FieldType.TEXT),
        PROFILE,
    )
    assert d.rule_id not in (
        "current_customer_or_client_no",
        "referred_by_employee_no",
        "current_employee_here_no",
        "previously_employed_here",
    )


def test_age_18_question_still_yields_yes_not_no():
    """The age_18_or_older rule auto-answers Yes; the new auto-No family
    must NOT preempt it."""
    d = resolve_field(
        _cand(
            label="Are you at least 18 years of age?",
            field_type=FieldType.RADIO,
            options=["Yes", "No"],
        ),
        PROFILE,
    )
    assert d.value == "Yes"
    assert d.rule_id == "age_18_or_older"


# ─── Field-type guard ───────────────────────────────────────────
def test_auto_no_does_not_fire_on_checkbox_layout():
    """Per the rule definitions, accepts_types is {SELECT, RADIO} only.
    Checkbox layouts repeat option text per checkbox and would create
    ambiguous matches (like the customPronounsOption issue)."""
    d = resolve_field(
        _cand(
            label="Are you a current customer?",
            field_type=FieldType.CHECKBOX,
            options=[],
        ),
        PROFILE,
    )
    assert d.rule_id != "current_customer_or_client_no", (
        "auto-No family must not match CHECKBOX layouts"
    )
