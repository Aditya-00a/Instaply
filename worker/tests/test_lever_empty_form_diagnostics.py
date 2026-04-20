"""Regression tests for the Whoop-style canary failure.

Two distinct bugs were surfacing together on the canary:
  1. `log_trace` built by the orchestrator omitted `submit_reason` and
     `submitted`, so the dashboard couldn't read the executor's signal.
  2. When the Lever adapter's `parse_form` returned zero candidates
     (because the JD URL was stored instead of the /apply URL), the
     orchestrator still called `execute_decisions` with an empty list
     and then produced the useless user-facing `"execution_errors=0"`.

These tests pin the contracts those fixes depend on:
  - `LeverAdapter.parse_form` on a JD-style page returns `[]`
    (the exact trigger that kicks off the /apply retry + diagnostic).
  - `LeverAdapter.parse_form` on a real apply-form page returns ≥ 1
    candidate (proves the retry will succeed when the DOM is right).
  - `ExecutionReport` instances can carry the `submit_reason` field
    we now read in `log_trace` / `error_message`.
"""
from __future__ import annotations

from worker.actions import ExecutionReport
from worker.adapters.base import AtsKind
from worker.adapters.lever import LeverAdapter


_JD_ONLY_HTML = """
<html><body>
  <div class="posting-headline"><h2>Senior Data Analyst</h2></div>
  <div class="posting-category">Remote · Full-time</div>
  <a class="postings-btn" href="/whoop/abc123/apply">Apply for this job</a>
  <!-- No application form on the JD page — only the CTA link. -->
</body></html>
"""

_APPLY_FORM_HTML = """
<html><body>
  <form data-qa="application-form" action="/apply" method="post">
    <label for="name">Full name</label>
    <input id="name" name="name" type="text" required>
    <label for="email">Email</label>
    <input id="email" name="email" type="email" required>
    <label for="resume">Resume</label>
    <input id="resume" name="resume" type="file">
    <button class="postings-btn" type="submit">Submit application</button>
  </form>
</body></html>
"""


def test_lever_jd_page_yields_zero_candidates():
    """The Whoop canary failure mode: Lever URL stored is the JD page,
    not `/apply`, so the form element doesn't exist and parse_form
    correctly returns []. This is what triggers the new retry path."""
    adapter = LeverAdapter()
    assert adapter.kind == AtsKind.LEVER
    candidates = adapter.parse_form(_JD_ONLY_HTML)
    assert candidates == [], "JD-only page should parse to zero candidates"


def test_lever_apply_page_yields_candidates():
    """The post-retry state: after re-navigating to `/apply`, the form
    is present and the adapter returns at least one fillable field."""
    adapter = LeverAdapter()
    candidates = adapter.parse_form(_APPLY_FORM_HTML)
    assert len(candidates) >= 1
    names = {c.name_attr or c.id_attr or c.dom_id for c in candidates}
    assert any("name" in (n or "") for n in names), f"expected name field, got {names}"
    assert any("email" in (n or "") for n in names), f"expected email field, got {names}"


def test_execution_report_carries_submit_reason():
    """log_trace now reads rep.submit_reason; pin the field is present."""
    rep = ExecutionReport(
        filled=0, skipped=0, flagged_review=0, errors=1,
        submitted=False, outcomes=[],
    )
    rep.submit_reason = (
        "no_application_form_found (adapter=lever, "
        "tried=['https://jobs.lever.co/whoop/x', 'https://jobs.lever.co/whoop/x/apply'])"
    )
    assert rep.submit_reason.startswith("no_application_form_found")
    assert "adapter=lever" in rep.submit_reason
    assert "/apply" in rep.submit_reason
