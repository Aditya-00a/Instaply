"""Lever adapter + engine pipeline — no network."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from worker.adapters import adapter_for_html, adapter_for_url
from worker.adapters.base import AtsKind
from worker.autofill import resolve_field
from worker.autofill.cache import MemoryAnswerCache
from worker.autofill.models import DecisionSource, FieldType, UserProfile

FIXTURE = Path(__file__).parent / "fixtures" / "lever_sample.html"


PROFILE = UserProfile(
    user_id="22222222-2222-2222-2222-222222222222",
    first_name="Aditya",
    last_name="Sakhale",
    full_name="Aditya Sakhale",
    email="aditya@example.com",
    phone_e164="+12125551234",
    linkedin_url="https://linkedin.com/in/aditya",
    github_url="https://github.com/aditya",
    portfolio_url="https://asion.ai",
    current_company="Ravendise",
    work_auth_status="opt",
    needs_sponsorship=True,
    degree="Master's",
    resume_local_path="/tmp/resume.pdf",
)


def test_detect_by_url():
    assert adapter_for_url("https://jobs.lever.co/beta/abc-123") is not None
    assert adapter_for_url("https://jobs.lever.co/beta/abc/apply") is not None


def test_detect_by_html():
    html = FIXTURE.read_text(encoding="utf-8")
    a = adapter_for_html(html)
    assert a is not None and a.kind == AtsKind.LEVER


def _parse():
    html = FIXTURE.read_text(encoding="utf-8")
    a = adapter_for_html(html)
    return a.parse_form(html, company_slug="beta")


def test_fixture_parses_expected_fields():
    cands = _parse()
    # 1 file + 6 user fields + 4 additional = 11 fields
    assert len(cands) >= 10


def test_labels_resolved_even_without_for_attr():
    """Lever labels don't use `for=` — we rely on .application-label walker."""
    cands = _parse()
    labels = {c.label for c in cands if c.label}
    assert "Full name" in labels
    assert any("authorized to work" in (c.label or "").lower() for c in cands)
    assert any("sponsorship" in (c.label or "").lower() for c in cands)


def test_full_pipeline():
    cands = _parse()
    decisions = {c.dom_id: resolve_field(c, PROFILE, cache=MemoryAnswerCache()) for c in cands}

    # Map by visible label for readability
    by_label = {c.label: decisions[c.dom_id] for c in cands if c.label}

    assert by_label["Full name"].value == "Aditya Sakhale"
    assert by_label["Email"].value == "aditya@example.com"
    assert by_label["Phone"].value == "+12125551234"
    assert by_label["Current company"].value == "Ravendise"
    assert "linkedin.com" in by_label["LinkedIn URL"].value
    assert "github.com" in by_label["GitHub URL"].value
    assert by_label["Portfolio URL"].value == "https://asion.ai"
    assert by_label["Resume/CV"].value == "/tmp/resume.pdf"
    assert by_label["Highest degree"].value == "Master's"

    # Work auth + sponsorship match by substring in label text
    for label, dec in by_label.items():
        if "authorized to work" in label.lower():
            assert dec.value == "Yes"
            assert dec.required_review is True
        if "sponsorship" in label.lower():
            assert dec.value == "Yes"
            assert dec.required_review is True

    # Free-text "Why" has no rule/cache/llm → REVIEW (not silent skip)
    for label, dec in by_label.items():
        if "why do you want to work" in label.lower():
            assert dec.source == DecisionSource.REVIEW


def test_required_never_silently_skipped():
    cands = _parse()
    for c in cands:
        d = resolve_field(c, PROFILE, cache=MemoryAnswerCache())
        if c.required:
            assert d.source != DecisionSource.SKIP, (
                f"Required field {c.label or c.dom_id!r} silently skipped"
            )
