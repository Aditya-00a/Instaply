"""Tests for actions._detect_confirmation and the execute_decisions
submit gate. We mock the Playwright page minimally — the helper only
touches page.url, page.text_content('body'), and page.wait_for_load_state.
"""
from __future__ import annotations

import asyncio
from typing import Optional


from worker.actions import (
    _detect_confirmation,
    execute_decisions,
)
from worker.autofill.models import (
    DecisionSource,
    FieldCandidate,
    FieldDecision,
    FieldType,
)


# ─── Minimal fake Playwright Page ────────────────────────────────
class FakePage:
    """Bare-minimum Page stand-in: configurable url + body text.

    Awaitable methods return canned values; counters let tests assert
    side effects without spinning up a real browser.
    """

    def __init__(
        self,
        *,
        url_before: str = "https://example.com/jobs/123",
        url_after: Optional[str] = None,
        body_text: str = "",
        click_raises: Optional[Exception] = None,
        html: str = "",
    ) -> None:
        self._current_url = url_before
        self._url_after = url_after if url_after is not None else url_before
        self._body_text = body_text
        self._click_raises = click_raises
        self._html = html
        self.click_calls: list[tuple[str, dict]] = []

    async def content(self) -> str:
        # Playwright's page.content() returns the full HTML; the
        # post-click block classifier consumes this for captcha
        # marker detection.
        return self._html

    @property
    def url(self) -> str:
        return self._current_url

    async def wait_for_load_state(self, state: str, timeout: int = 0) -> None:
        # Simulate the post-click URL transition completing on settle.
        self._current_url = self._url_after

    async def text_content(self, selector: str) -> str:
        assert selector == "body"
        return self._body_text

    async def click(self, selector: str, timeout: int = 0) -> None:
        self.click_calls.append((selector, {"timeout": timeout}))
        if self._click_raises is not None:
            raise self._click_raises


def _run(coro):
    # asyncio.run creates a fresh loop per call — Py 3.14 no longer
    # auto-creates one for asyncio.get_event_loop().
    return asyncio.run(coro)


# ─── _detect_confirmation ────────────────────────────────────────
def test_text_signal_thank_you_for_applying_marks_confirmed():
    page = FakePage(body_text="Thank you for applying! We'll be in touch.")
    confirmed, reason = _run(_detect_confirmation(page, url_before=page.url))
    assert confirmed is True
    assert reason.startswith("text_signal:")
    assert "thank you for applying" in reason.lower()


def test_text_signal_application_received_marks_confirmed():
    page = FakePage(body_text="Your application has been received.")
    confirmed, reason = _run(_detect_confirmation(page, url_before=page.url))
    assert confirmed is True
    assert "received" in reason.lower()


def test_url_change_to_thanks_marks_confirmed():
    page = FakePage(
        url_before="https://boards.greenhouse.io/acme/jobs/123",
        url_after="https://boards.greenhouse.io/acme/thanks/123",
        body_text="",
    )
    confirmed, reason = _run(_detect_confirmation(page, url_before="https://boards.greenhouse.io/acme/jobs/123"))
    assert confirmed is True
    assert reason == "url_signal:thanks"


def test_url_change_with_application_complete_segment():
    page = FakePage(
        url_before="https://jobs.lever.co/acme/123",
        url_after="https://jobs.lever.co/acme/123/application-complete",
        body_text="",
    )
    confirmed, reason = _run(_detect_confirmation(page, url_before="https://jobs.lever.co/acme/123"))
    assert confirmed is True
    assert reason in {"url_signal:complete", "url_signal:application-complete"}


def test_no_signal_returns_unconfirmed():
    page = FakePage(
        url_before="https://boards.greenhouse.io/acme/jobs/123",
        url_after="https://boards.greenhouse.io/acme/jobs/123",
        body_text="Please fix the errors below.",
    )
    confirmed, reason = _run(_detect_confirmation(page, url_before=page.url))
    assert confirmed is False
    assert reason == "no_confirmation_signal"


def test_url_segment_match_does_not_trip_on_substring():
    """'thanks' should match a literal 'thanks' segment, not 'thanksgiving'."""
    page = FakePage(
        url_before="https://example.com/jobs/123",
        url_after="https://example.com/thanksgivingsale/promo",
        body_text="Form errors: phone is required.",
    )
    confirmed, reason = _run(_detect_confirmation(page, url_before="https://example.com/jobs/123"))
    assert confirmed is False
    assert reason == "no_confirmation_signal"


def test_text_signal_takes_priority_over_url_unchanged():
    page = FakePage(
        url_before="https://example.com/jobs/123",
        url_after="https://example.com/jobs/123",
        body_text="<header> Submission successful </header>",
    )
    confirmed, reason = _run(_detect_confirmation(page, url_before=page.url))
    assert confirmed is True
    assert reason.startswith("text_signal:")


# ─── execute_decisions submit gate ───────────────────────────────
def _trivial_decision_and_candidate():
    cand = FieldCandidate(
        dom_id="email", field_type=FieldType.EMAIL, label="Email", id_attr="email", required=True,
    )
    dec = FieldDecision(
        dom_id="email", value="user@example.com", source=DecisionSource.RULE, confidence=1.0,
    )
    return [dec], [cand]


def test_submit_gate_marks_unconfirmed_when_page_unchanged():
    """Click succeeds, page didn't change, no confirmation phrase: NOT submitted."""
    decisions, candidates = _trivial_decision_and_candidate()
    page = FakePage(
        url_before="https://boards.greenhouse.io/acme/jobs/123",
        url_after="https://boards.greenhouse.io/acme/jobs/123",
        body_text="Please complete required fields.",
    )

    # Patch _fill_text so we don't try to fill against the fake page
    from worker import actions

    async def _noop(*a, **kw):
        return None

    orig_fill = actions._fill_text
    actions._fill_text = _noop
    try:
        report = _run(execute_decisions(page, decisions, candidates))
    finally:
        actions._fill_text = orig_fill

    assert report.submitted is False
    # submit_reason now stitches the matched selector onto the reason
    # (e.g. "no_confirmation_signal via button[type='submit']") so audit
    # logs can pinpoint which click landed.
    assert (report.submit_reason or "").startswith("no_confirmation_signal")
    assert page.click_calls, "submit_selector should have been clicked"


def test_submit_gate_marks_submitted_on_text_signal():
    decisions, candidates = _trivial_decision_and_candidate()
    page = FakePage(
        url_before="https://boards.greenhouse.io/acme/jobs/123",
        url_after="https://boards.greenhouse.io/acme/jobs/123",
        body_text="Thank you for applying. We will be in touch.",
    )

    from worker import actions

    async def _noop(*a, **kw):
        return None

    orig_fill = actions._fill_text
    actions._fill_text = _noop
    try:
        report = _run(execute_decisions(page, decisions, candidates))
    finally:
        actions._fill_text = orig_fill

    assert report.submitted is True
    assert report.submit_reason and report.submit_reason.startswith("text_signal:")


def test_submit_gate_records_click_failure_reason():
    decisions, candidates = _trivial_decision_and_candidate()
    page = FakePage(
        click_raises=RuntimeError("element is detached from the DOM"),
    )

    from worker import actions

    async def _noop(*a, **kw):
        return None

    orig_fill = actions._fill_text
    actions._fill_text = _noop
    try:
        report = _run(execute_decisions(page, decisions, candidates))
    finally:
        actions._fill_text = orig_fill

    assert report.submitted is False
    assert report.submit_reason and report.submit_reason.startswith("submit_click_failed:")
    assert "detached" in report.submit_reason


def test_submit_gate_skipped_in_dry_run():
    decisions, candidates = _trivial_decision_and_candidate()
    page = FakePage()

    from worker import actions

    async def _noop(*a, **kw):
        return None

    orig_fill = actions._fill_text
    actions._fill_text = _noop
    try:
        report = _run(execute_decisions(page, decisions, candidates, dry_run=True))
    finally:
        actions._fill_text = orig_fill

    assert report.submitted is False
    assert report.submit_reason is None
    assert not page.click_calls


# ─── Captcha / verification classification ───────────────────────
def test_hcaptcha_marker_classifies_as_captcha_required():
    """Lever-style hCaptcha gate after a click that didn't navigate
    and didn't surface a 'thank you' state."""
    html = """
    <html><body>
      <div class="hcaptcha-widget" data-sitekey="abc123"></div>
      <script src="https://hcaptcha.com/1/api.js"></script>
      <iframe src="https://hcaptcha.com/captcha/v1/abc"></iframe>
    </body></html>
    """
    page = FakePage(body_text="", html=html)
    confirmed, reason = _run(_detect_confirmation(page, url_before=page.url))
    assert confirmed is False
    assert reason == "captcha_required"


def test_recaptcha_enterprise_marker_classifies_as_verification_required():
    """Greenhouse-style reCAPTCHA Enterprise after click without nav."""
    html = """
    <html><body>
      <script>
        window.ENV = {
          "GOOGLE_RECAPTCHA_INVISIBLE_KEY": "6LfmcbcpAAAAAChNTbhUShzUOAMj_wY9LQIvLFX0",
          "GOOGLE_RECAPTCHA_ENDPOINT": "https://www.recaptcha.net/recaptcha/enterprise.js"
        };
      </script>
    </body></html>
    """
    page = FakePage(body_text="", html=html)
    confirmed, reason = _run(_detect_confirmation(page, url_before=page.url))
    assert confirmed is False
    assert reason == "verification_required"


def test_no_captcha_marker_falls_back_to_no_confirmation_signal():
    """Plain failed submit with no captcha and no thank-you state →
    keep the existing generic reason so existing dashboards don't
    silently change behavior for non-captcha failures."""
    html = "<html><body><p>Please fill in all required fields.</p></body></html>"
    page = FakePage(body_text="please fill in all required fields.", html=html)
    confirmed, reason = _run(_detect_confirmation(page, url_before=page.url))
    assert confirmed is False
    assert reason == "no_confirmation_signal"


def test_text_signal_wins_over_captcha_classification():
    """If the page genuinely shows 'Thank you' AND has captcha
    scaffolding (Greenhouse keeps the recaptcha script on the
    confirmation page too), the success signal must still win."""
    html = """
    <html><body>
      <h1>Thank you for applying</h1>
      <script src="https://www.recaptcha.net/recaptcha/enterprise.js"></script>
    </body></html>
    """
    page = FakePage(body_text="Thank you for applying! We'll be in touch.", html=html)
    confirmed, reason = _run(_detect_confirmation(page, url_before=page.url))
    assert confirmed is True
    assert reason.startswith("text_signal:")


def test_hcaptcha_takes_precedence_over_recaptcha_when_both_present():
    """Some pages ship both vendor scripts; hCaptcha is the more
    aggressive of the two and is checked first."""
    html = """
    <div class="h-captcha" data-sitekey="x"></div>
    <script src="https://hcaptcha.com/1/api.js"></script>
    <script src="https://www.recaptcha.net/recaptcha/enterprise.js"></script>
    """
    page = FakePage(body_text="", html=html)
    confirmed, reason = _run(_detect_confirmation(page, url_before=page.url))
    assert confirmed is False
    assert reason == "captcha_required"
