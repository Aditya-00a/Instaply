"""Greenhouse adapter + full engine pipeline against a realistic fixture.

Proves: HTML -> FieldCandidate[] -> FieldDecision[] works end-to-end
with zero network calls.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from worker.adapters import adapter_for_html, adapter_for_url
from worker.adapters.base import AtsKind
from worker.autofill import resolve_field
from worker.autofill.cache import MemoryAnswerCache
from worker.autofill.models import DecisionSource, UserProfile

FIXTURE = Path(__file__).resolve().parents[1] / "worker" / "tests" / "fixtures" / "greenhouse_sample.html"


PROFILE = UserProfile(
    user_id="11111111-1111-1111-1111-111111111111",
    first_name="Jordan",
    last_name="Lee",
    full_name="Jordan Lee",
    email="jordan.lee@example.com",
    phone_e164="+12125551234",
    linkedin_url="https://linkedin.com/in/jordan-lee",
    github_url="https://github.com/jordanlee",
    portfolio_url="https://asion.ai",
    city="New York",
    state="NY",
    country="United States",
    work_auth_status="opt",
    needs_sponsorship=True,
    school="New York University",
    degree="Master's",
    major="Computer Science",
    gender="Male",
    race_ethnicity="Asian",
    veteran_status="I am not a protected veteran",
    disability_status="No, I do not have a disability",
    resume_local_path="/tmp/resume.pdf",
    cover_letter_local_path="/tmp/cover.pdf",
)


def test_detect_by_url():
    gh1 = adapter_for_url("https://boards.greenhouse.io/acme/jobs/12345")
    gh2 = adapter_for_url("https://acme.greenhouse.io/jobs/12345")
    assert gh1 is not None and gh1.kind == AtsKind.GREENHOUSE
    assert gh2 is not None and gh2.kind == AtsKind.GREENHOUSE
    # Lever URL should NOT be detected as Greenhouse
    lv = adapter_for_url("https://jobs.lever.co/acme/x")
    assert lv is None or lv.kind != AtsKind.GREENHOUSE


def test_detect_by_html():
    html = FIXTURE.read_text(encoding="utf-8")
    adapter = adapter_for_html(html)
    assert adapter is not None
    assert adapter.kind == AtsKind.GREENHOUSE


def _parse() -> list:
    html = FIXTURE.read_text(encoding="utf-8")
    adapter = adapter_for_html(html)
    return adapter.parse_form(html, company_slug="acme")


def test_fixture_parses_to_expected_field_count():
    cands = _parse()
    # Expect: 4 contact + 2 files + 3 links + 1 location + 6 custom + 4 eeo = 20
    # The exact count may vary slightly as we tune skip rules; assert minimum.
    assert len(cands) >= 18, f"Expected >=18 fields, got {len(cands)}"


def test_required_flags_propagate():
    cands = {c.id_attr: c for c in _parse() if c.id_attr}
    assert cands["first_name"].required is True
    assert cands["last_name"].required is True
    assert cands["email"].required is True
    assert cands["phone"].required is False
    assert cands["resume"].required is True
    assert cands["cover_letter"].required is False
    assert cands["q_why"].required is True
    assert cands["q_work_auth"].required is True
    assert cands["q_sponsor"].required is True
    # EEO fields are optional
    assert cands["gender"].required is False


def test_select_options_extracted():
    cands = {c.id_attr: c for c in _parse() if c.id_attr}
    assert "Yes" in cands["q_work_auth"].options
    assert "No" in cands["q_work_auth"].options
    assert "Asian" in cands["race"].options
    assert "I am not a protected veteran" in cands["veteran_status"].options


def test_full_engine_pipeline_against_fixture():
    """The money test: parse -> resolve -> assert every critical field is filled."""
    cands = _parse()
    decisions = {c.dom_id: resolve_field(c, PROFILE, cache=MemoryAnswerCache()) for c in cands}

    # Index by id_attr for readability
    by_id = {}
    for c in cands:
        if c.id_attr:
            by_id[c.id_attr] = decisions[c.dom_id]

    # Contact block — all rules, all high confidence
    assert by_id["first_name"].source == DecisionSource.RULE
    assert by_id["first_name"].value == "Jordan"
    assert by_id["last_name"].value == "Lee"
    assert by_id["email"].value == "jordan.lee@example.com"
    assert by_id["phone"].value == "+12125551234"

    # Resume + cover letter
    assert by_id["resume"].source == DecisionSource.RULE
    assert by_id["resume"].value == "/tmp/resume.pdf"
    assert by_id["cover_letter"].value == "/tmp/cover.pdf"

    # Links
    assert "linkedin.com" in by_id["urls_linkedin"].value
    assert "github.com" in by_id["urls_github"].value
    assert by_id["urls_portfolio"].value == "https://asion.ai"

    # Work auth + sponsorship — dynamic-review semantics (added 2026-04-18):
    # - work_auth on profile.work_auth_status='opt' is ambiguous → review.
    # - sponsorship with explicit needs_sponsorship=True → auto-answer.
    assert by_id["q_work_auth"].value == "Yes"
    assert by_id["q_work_auth"].required_review is True
    assert by_id["q_sponsor"].value == "Yes"
    assert by_id["q_sponsor"].required_review is False

    # Education
    assert by_id["q_school"].value == "New York University"
    assert by_id["q_degree"].value == "Master's"
    assert by_id["q_major"].value == "Computer Science"

    # EEO
    assert by_id["gender"].value == "Male"
    assert by_id["race"].value == "Asian"
    assert by_id["veteran_status"].value == "I am not a protected veteran"

    # The free-text "Why do you want to work at Acme?" has no rule + no cache + no LLM
    # -> required REVIEW (not a silent failure)
    assert by_id["q_why"].source == DecisionSource.REVIEW
    assert by_id["q_why"].required_review is True


def test_critical_required_fields_are_covered_or_flagged():
    """Every required field must end up either filled (rule/cache/llm) or flagged REVIEW.
    A required field ending in SKIP would be a silent failure — forbidden."""
    cands = _parse()
    decisions = [resolve_field(c, PROFILE, cache=MemoryAnswerCache()) for c in cands]
    for cand, dec in zip(cands, decisions):
        if cand.required:
            assert dec.source != DecisionSource.SKIP, (
                f"Required field {cand.id_attr or cand.dom_id!r} silently skipped — not allowed"
            )
