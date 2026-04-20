"""SmartRecruiters adapter smoke test."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from worker.adapters import adapter_for_html, adapter_for_url
from worker.adapters.base import AtsKind
from worker.autofill import resolve_field
from worker.autofill.cache import MemoryAnswerCache
from worker.autofill.models import DecisionSource, UserProfile

FIXTURE = Path(__file__).resolve().parents[1] / "worker" / "tests" / "fixtures" / "smartrecruiters_sample.html"


PROFILE = UserProfile(
    user_id="33333333-3333-3333-3333-333333333333",
    first_name="Jordan",
    last_name="Lee",
    full_name="Jordan Lee",
    email="jordan.lee@example.com",
    phone_e164="+12125551234",
    linkedin_url="https://linkedin.com/in/jordan-lee",
    work_auth_status="opt",
    needs_sponsorship=True,
    degree="Master's",
    resume_local_path="/tmp/resume.pdf",
)


def test_detect_url():
    a = adapter_for_url("https://jobs.smartrecruiters.com/GammaCorp/abc")
    assert a is not None and a.kind == AtsKind.SMARTRECRUITERS


def test_detect_html():
    html = FIXTURE.read_text(encoding="utf-8")
    a = adapter_for_html(html)
    assert a is not None and a.kind == AtsKind.SMARTRECRUITERS


def _parse():
    html = FIXTURE.read_text(encoding="utf-8")
    return adapter_for_html(html).parse_form(html, company_slug="gamma")


def test_full_pipeline():
    cands = _parse()
    by_id = {c.id_attr: c for c in cands if c.id_attr}
    decisions = {c.dom_id: resolve_field(c, PROFILE, cache=MemoryAnswerCache()) for c in cands}

    assert decisions[by_id["firstName"].dom_id].value == "Jordan"
    assert decisions[by_id["lastName"].dom_id].value == "Lee"
    assert decisions[by_id["email"].dom_id].value == "jordan.lee@example.com"
    assert decisions[by_id["phone"].dom_id].value == "+12125551234"
    assert "linkedin.com" in decisions[by_id["linkedin"].dom_id].value
    assert decisions[by_id["resume"].dom_id].value == "/tmp/resume.pdf"

    # Screening questions
    assert decisions[by_id["q_auth"].dom_id].value == "Yes"
    assert decisions[by_id["q_auth"].dom_id].required_review is True
    assert decisions[by_id["q_spon"].dom_id].value == "Yes"
    assert decisions[by_id["q_degree"].dom_id].value == "Master's"


def test_required_never_silently_skipped():
    cands = _parse()
    for c in cands:
        d = resolve_field(c, PROFILE, cache=MemoryAnswerCache())
        if c.required:
            assert d.source != DecisionSource.SKIP
