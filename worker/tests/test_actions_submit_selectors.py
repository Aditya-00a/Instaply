"""Tests for adapter-aware submit selectors.

Covers three things explicitly required by the task:
  1. Adapter-provided selectors are tried (and the right one wins).
  2. When no adapter selectors are passed, the executor falls back to
     the conservative DEFAULT_SUBMIT_SELECTORS.
  3. Lever-style submit buttons (`button.template-btn-submit`,
     `button.postings-btn`, custom-text variants) are matched by the
     LeverAdapter's selectors.
"""
from __future__ import annotations

import asyncio
from typing import Optional

import pytest

from worker.actions import (
    DEFAULT_SUBMIT_SELECTORS,
    _click_first_match,
    execute_decisions,
)
from worker.adapters.base import DEFAULT_SUBMIT_SELECTORS as BASE_DEFAULT
from worker.adapters.greenhouse import GreenhouseAdapter
from worker.adapters.lever import LeverAdapter
from worker.adapters.smartrecruiters import SmartRecruitersAdapter
from worker.autofill.models import (
    DecisionSource,
    FieldCandidate,
    FieldDecision,
    FieldType,
)


# ─── Page mock that recognises a finite set of selectors ────────
class SelectorAwarePage:
    """Page mock where only a configured subset of selectors will 'click'.

    Mirrors Playwright's contract just enough for actions.py:
      - .click(sel, timeout=...)         -> raises unless sel in matchable
      - .url                             -> changing per `url_after`
      - .wait_for_load_state(...)        -> swaps to url_after
      - .text_content('body')            -> returns body_text
    """

    def __init__(
        self,
        *,
        matchable: set[str],
        url_before: str = "https://example.com/jobs/1",
        url_after: Optional[str] = None,
        body_text: str = "Thank you for applying.",
    ) -> None:
        self._matchable = set(matchable)
        self._url = url_before
        self._url_after = url_after if url_after is not None else url_before
        self._body_text = body_text
        self.click_attempts: list[str] = []

    @property
    def url(self) -> str:
        return self._url

    async def click(self, sel: str, timeout: int = 0) -> None:
        self.click_attempts.append(sel)
        if sel not in self._matchable:
            raise RuntimeError(f"no element for selector {sel!r}")

    async def wait_for_load_state(self, state: str, timeout: int = 0) -> None:
        self._url = self._url_after

    async def text_content(self, selector: str) -> str:
        assert selector == "body"
        return self._body_text


def _run(coro):
    return asyncio.run(coro)


def _trivial_decision_and_candidate():
    cand = FieldCandidate(
        dom_id="email", field_type=FieldType.EMAIL, label="Email",
        id_attr="email", required=True,
    )
    dec = FieldDecision(
        dom_id="email", value="user@example.com",
        source=DecisionSource.RULE, confidence=1.0,
    )
    return [dec], [cand]


def _patch_fill_text_noop():
    """Stop _fill_text from talking to the fake page during execute_decisions."""
    from worker import actions as _actions

    async def _noop(*a, **kw):
        return None

    orig = _actions._fill_text
    _actions._fill_text = _noop
    return orig


def _restore_fill_text(orig):
    from worker import actions as _actions
    _actions._fill_text = orig


# ─── _click_first_match ──────────────────────────────────────────
def test_click_first_match_picks_first_landing_selector():
    page = SelectorAwarePage(matchable={"button.postings-btn:has-text('Submit')"})
    selectors = [
        "button.template-btn-submit",          # not on this page
        "button.postings-btn:has-text('Submit')",  # this should win
        "button[type='submit']",
    ]
    clicked, used, last_err = _run(_click_first_match(page, selectors))
    assert clicked is True
    assert used == "button.postings-btn:has-text('Submit')"
    # We attempted the prior one and failed before landing on the second
    assert page.click_attempts == [
        "button.template-btn-submit",
        "button.postings-btn:has-text('Submit')",
    ]


def test_click_first_match_returns_false_when_nothing_matches():
    page = SelectorAwarePage(matchable=set())
    selectors = ["a", "b", "c"]
    clicked, used, last_err = _run(_click_first_match(page, selectors))
    assert clicked is False
    assert used is None
    assert last_err is not None and "c" in last_err


# ─── Force-click fallback (rescues "resolved but unclickable") ───
class _ForceClickPage:
    """Page mock where a selector RESOLVES (Playwright finds the element)
    but the normal click times out — like a button covered by a transient
    overlay or with `pointer-events:none`. Only `force=True` clicks land.

    This mirrors the real-world Lever situation where the submit button is
    on the page and intended to be clicked, but Playwright's actionability
    check refuses to commit until the overlay/captcha widget settles.
    """

    def __init__(self, *, resolves: set[str], force_only: set[str]) -> None:
        self._resolves = set(resolves)
        self._force_only = set(force_only)
        self.click_attempts: list[tuple[str, bool]] = []

    async def click(self, sel: str, timeout: int = 0, force: bool = False) -> None:
        self.click_attempts.append((sel, force))
        if sel in self._force_only:
            if force:
                return
            # Mimic Playwright's exact wording so _click_first_match's
            # "locator resolved to" detection fires.
            raise RuntimeError(
                f"Page.click: Timeout {timeout}ms exceeded.\n"
                f"Call log:\n  - waiting for locator({sel!r})\n"
                f"  - locator resolved to <button id=\"btn-submit\" type=\"button\">"
            )
        if sel in self._resolves:
            return
        raise RuntimeError(f"no element for selector {sel!r}")


def test_force_click_fallback_rescues_resolved_but_unclickable_button():
    """The exact f27fd5ef failure shape: every normal click times out
    with `locator resolved to <button …>`. The fallback must retry the
    first resolving selector with force=True and succeed."""
    page = _ForceClickPage(
        resolves=set(),
        force_only={"button[data-qa='btn-submit']:not(.hidden)"},
    )
    selectors = [
        "button[data-qa='btn-submit']:not(.hidden)",
        "button#btn-submit:not(.hidden)",
        "button.template-btn-submit:not(.hidden)",
    ]
    clicked, used, last_err = _run(_click_first_match(page, selectors, per_selector_timeout_ms=10))
    assert clicked is True
    assert used == "button[data-qa='btn-submit']:not(.hidden) (force)"
    # Every normal selector must have been tried first; force is last resort.
    forces = [s for s, f in page.click_attempts if f]
    assert len(forces) == 1
    assert forces[0] == "button[data-qa='btn-submit']:not(.hidden)"


def test_force_click_fallback_does_not_fire_when_no_selector_resolved():
    """If NO selector resolved an element (the button just isn't on the
    page), force-click must NOT be tried — there's nothing safe to force."""
    page = _ForceClickPage(resolves=set(), force_only=set())
    clicked, used, last_err = _run(_click_first_match(
        page, ["button#nope", "button#also-nope"], per_selector_timeout_ms=10,
    ))
    assert clicked is False
    assert used is None
    # No force=True attempts should appear.
    assert all(not f for _, f in page.click_attempts)


# ─── Adapter selectors are non-empty ─────────────────────────────
def test_each_adapter_exposes_a_non_empty_submit_selectors_list():
    for adapter_cls in (GreenhouseAdapter, LeverAdapter, SmartRecruitersAdapter):
        sel = getattr(adapter_cls, "submit_selectors", None)
        assert isinstance(sel, list), f"{adapter_cls.__name__} missing submit_selectors"
        assert len(sel) > 0, f"{adapter_cls.__name__} submit_selectors is empty"
        assert all(isinstance(s, str) and s for s in sel)


def test_lever_selectors_cover_known_submit_button_shapes():
    """Lever buttons we care about: stable `data-qa` and `#id` markers
    first, then class-based, then text-based. The bare
    `button[type='submit']` selector is intentionally NOT in the Lever
    list — it matches Lever's hidden hCaptcha helper button and burns
    the per-selector budget (root cause of the 2026-04-18 incident).
    """
    sels = LeverAdapter.submit_selectors
    joined = "\n".join(sels)
    assert "data-qa='btn-submit'" in joined or 'data-qa="btn-submit"' in joined
    assert "#btn-submit" in joined
    assert "template-btn-submit" in joined
    assert "postings-btn" in joined
    assert any("Submit" in s for s in sels)
    # Regression guard: the bare `button[type='submit']` selector is NOT
    # allowed in Lever's list — it sinks time into the hidden hCaptcha
    # helper. The DEFAULT_SUBMIT_SELECTORS still include it for ATSes
    # that genuinely use it.
    assert "button[type='submit']" not in sels, (
        "Lever's submit_selectors must not contain the bare "
        "button[type='submit'] — it matches the hidden hCaptcha helper "
        "(see lever.py docstring)."
    )
    # Every Lever selector must guard against `.hidden` so we never click
    # the hidden hCaptcha button even by accident through a class match.
    for s in sels:
        assert ":not(.hidden)" in s, (
            f"Lever selector {s!r} is missing :not(.hidden); a hidden "
            "matching element will time out the click."
        )


def test_greenhouse_selectors_cover_legacy_input_and_remix_button():
    sels = GreenhouseAdapter.submit_selectors
    assert any("input[type='submit']" in s for s in sels), "missing legacy <input type=submit>"
    assert any(s.startswith("button[type='submit']") for s in sels), "missing modern <button type=submit>"
    assert any("[data-qa='submit-button']" in s for s in sels)


def test_smartrecruiters_selectors_include_apply_and_im_interested():
    sels = SmartRecruitersAdapter.submit_selectors
    joined = "\n".join(sels)
    assert "i-am-interested" in joined.lower() or "i'm interested" in joined.lower()
    assert "Apply" in joined or "Submit" in joined


# ─── execute_decisions: adapter selectors override default ───────
def test_execute_decisions_uses_lever_selectors_when_provided():
    """LeverAdapter.submit_selectors must reach the page even when the
    page only responds to a Lever-specific selector."""
    decisions, candidates = _trivial_decision_and_candidate()
    page = SelectorAwarePage(
        # Lever's leading selector after the 2026-04-18 fix.
        matchable={"button[data-qa='btn-submit']:not(.hidden)"},
        body_text="Thank you for applying.",
    )

    orig = _patch_fill_text_noop()
    try:
        report = _run(execute_decisions(
            page, decisions, candidates,
            submit_selectors=LeverAdapter.submit_selectors,
        ))
    finally:
        _restore_fill_text(orig)

    assert report.submitted is True, report.submit_reason
    # The reason string carries the matched selector
    assert "via button[data-qa='btn-submit']:not(.hidden)" in (report.submit_reason or "")


def test_execute_decisions_uses_greenhouse_selectors_for_data_qa_button():
    decisions, candidates = _trivial_decision_and_candidate()
    page = SelectorAwarePage(
        matchable={"[data-qa='submit-button']"},
        body_text="Application submitted.",
    )

    orig = _patch_fill_text_noop()
    try:
        report = _run(execute_decisions(
            page, decisions, candidates,
            submit_selectors=GreenhouseAdapter.submit_selectors,
        ))
    finally:
        _restore_fill_text(orig)

    assert report.submitted is True, report.submit_reason
    assert "via [data-qa='submit-button']" in (report.submit_reason or "")


# ─── Default fallback when no adapter selectors are given ────────
def test_execute_decisions_falls_back_to_default_when_no_selectors_given():
    """submit_selectors=None must use DEFAULT_SUBMIT_SELECTORS."""
    decisions, candidates = _trivial_decision_and_candidate()
    page = SelectorAwarePage(
        matchable={"button[type='submit']"},   # in the default list
        body_text="Thank you for applying.",
    )

    orig = _patch_fill_text_noop()
    try:
        report = _run(execute_decisions(
            page, decisions, candidates,
            submit_selectors=None,
        ))
    finally:
        _restore_fill_text(orig)

    assert report.submitted is True, report.submit_reason
    assert "via button[type='submit']" in (report.submit_reason or "")


def test_default_constant_re_export_matches_base():
    """Backward-compatibility: the executor re-exports the same default
    list it imports from the adapters package, so callers can reference
    either."""
    assert DEFAULT_SUBMIT_SELECTORS == BASE_DEFAULT
    assert "button[type='submit']" in DEFAULT_SUBMIT_SELECTORS
    assert "input[type='submit']" in DEFAULT_SUBMIT_SELECTORS


def test_no_selector_matches_records_helpful_failure():
    """When neither the adapter list nor the default list matches, the
    submit_reason should clearly indicate the click never landed."""
    decisions, candidates = _trivial_decision_and_candidate()
    page = SelectorAwarePage(matchable=set())  # nothing matches

    orig = _patch_fill_text_noop()
    try:
        report = _run(execute_decisions(
            page, decisions, candidates,
            submit_selectors=LeverAdapter.submit_selectors,
        ))
    finally:
        _restore_fill_text(orig)

    assert report.submitted is False
    assert report.submit_reason is not None
    assert "submit_click_failed" in report.submit_reason
    assert "no selector matched" in report.submit_reason
