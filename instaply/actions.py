"""Playwright executor: takes a list of FieldDecision and fills the live form.

This is the ONLY module in the worker that touches Playwright directly.
Everything upstream (adapters, engine, rules, LLM) works on HTML strings
and pure data — making it testable without a browser.

Contract:
  execute_decisions(page, decisions, candidates, dry_run=False) -> ExecutionReport

`dry_run=True` fills every field but NEVER clicks submit — used for
review-before-send and for shadow-mode CI runs.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

from .adapters.base import DEFAULT_SUBMIT_SELECTORS
from .autofill.models import DecisionSource, FieldCandidate, FieldDecision, FieldType

log = logging.getLogger(__name__)


# ─── Report types ────────────────────────────────────────────────
@dataclass
class FieldOutcome:
    dom_id: str
    ok: bool
    action: str                      # 'fill' | 'select' | 'check' | 'upload' | 'skip' | 'review'
    error: Optional[str] = None


@dataclass
class ExecutionReport:
    filled: int = 0
    skipped: int = 0
    flagged_review: int = 0
    errors: int = 0
    submitted: bool = False
    # Why submitted ended up True or False — written for every non-dry-run
    # finalization. Examples:
    #   "text_signal:'thank you for applying'"
    #   "url_signal:thanks"
    #   "no_confirmation_signal"
    #   "submit_click_failed: <browser error>"
    # None when dry-run or when submit was skipped due to required-review.
    submit_reason: Optional[str] = None
    outcomes: list[FieldOutcome] = field(default_factory=list)

    def add(self, outcome: FieldOutcome) -> None:
        self.outcomes.append(outcome)
        if outcome.action == "skip":
            self.skipped += 1
        elif outcome.action == "review":
            self.flagged_review += 1
        elif outcome.ok:
            self.filled += 1
        else:
            self.errors += 1


# ─── Selector resolution ─────────────────────────────────────────
def _primary_selector(cand: FieldCandidate) -> str:
    """Best-effort selector. Prefer ID, then name-attr, then dom_id."""
    if cand.id_attr:
        return f"#{_css_escape(cand.id_attr)}"
    if cand.field_type == FieldType.CHECKBOX and cand.name_attr:
        return f'input[type="checkbox"][name="{_css_escape_attr(cand.name_attr)}"]'
    if cand.name_attr:
        return f'[name="{_css_escape_attr(cand.name_attr)}"]'
    return f"#{_css_escape(cand.dom_id)}"


def _css_escape(s: str) -> str:
    # Minimal CSS identifier escape — covers the attrs Greenhouse/Lever emit.
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("[", "\\[").replace("]", "\\]")


def _css_escape_attr(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


# ─── Per-field handlers ──────────────────────────────────────────
async def _fill_text(page, sel: str, value: str) -> None:
    await page.fill(sel, str(value), timeout=8000)


async def _select(page, sel: str, value: str) -> None:
    # Try label match, then value match, then visible text
    try:
        await page.select_option(sel, label=value, timeout=5000)
        return
    except Exception:
        pass
    try:
        await page.select_option(sel, value=value, timeout=5000)
        return
    except Exception:
        pass
    # Last resort: find option by text content
    await page.evaluate(
        """({sel, value}) => {
            const el = document.querySelector(sel);
            if (!el) return;
            for (const opt of el.options) {
              if (opt.text.trim().toLowerCase() === value.trim().toLowerCase()) {
                el.value = opt.value;
                el.dispatchEvent(new Event('change', { bubbles: true }));
                return;
              }
            }
        }""",
        {"sel": sel, "value": value},
    )


async def _check_radio(page, cand: FieldCandidate, value: str) -> None:
    """Click the radio whose visible label matches `value`."""
    name = cand.name_attr
    if not name:
        raise RuntimeError("radio without name attr")
    # Prefer label text match via label[for=id]
    await page.evaluate(
        """({name, value}) => {
            const radios = Array.from(document.querySelectorAll(`input[type=radio][name="${CSS.escape(name)}"]`));
            const target = value.trim().toLowerCase();
            for (const r of radios) {
              const lbl = r.id ? document.querySelector(`label[for="${CSS.escape(r.id)}"]`) : r.closest('label');
              const text = (lbl ? lbl.innerText : r.value || '').trim().toLowerCase();
              if (text === target || text.includes(target) || target.includes(text)) {
                r.checked = true;
                r.dispatchEvent(new Event('change', { bubbles: true }));
                return;
              }
            }
        }""",
        {"name": name, "value": value},
    )


async def _check_checkbox(page, sel: str, value) -> None:
    should_check = bool(value) and str(value).lower() not in ("false", "no", "0", "")
    if should_check:
        await page.check(sel, timeout=5000)
    else:
        await page.uncheck(sel, timeout=5000)


async def _upload(page, sel: str, path: str) -> None:
    await page.set_input_files(sel, path, timeout=10000)


# ─── Submit confirmation detection ───────────────────────────────
# We mark `submitted=True` only when the post-click page shows positive
# evidence the ATS accepted the application. A successful click on a
# submit button proves nothing — server-side validation, captchas, and
# silent rejections all let the click "succeed" while no submission
# actually happened. Tying credit deduction to a real signal keeps the
# "$1 per confirmed application" promise honest.

# Lowercased substrings; conservative — only phrases that almost never
# appear on a still-blank application form.
_CONFIRMATION_TEXT_SIGNALS: tuple[str, ...] = (
    "thank you for applying",
    "thanks for applying",
    "application received",
    "application submitted",
    "successfully submitted",
    "your application has been received",
    "your application was submitted",
    "we have received your application",
    "we'll be in touch",
    "we will be in touch",
    "submission successful",
    "thanks for your interest",
)

# URL path tokens that ATS systems commonly redirect to on success.
# Matched against the first path segment after a URL change so we don't
# trip on incidental occurrences inside long form URLs.
_CONFIRMATION_URL_TOKENS: tuple[str, ...] = (
    "thanks",
    "thank-you",
    "thank_you",
    "thankyou",
    "confirmation",
    "confirmed",
    "success",
    "submitted",
    "submission",
    "applied",
    "application-complete",
    "complete",
    "received",
)


# Markers we look for in the post-click DOM to distinguish a real
# captcha/verification wall from a generic "no confirmation" failure.
# Sourced from the 2026-04-19 artifact pass on `6b0f1c74` (Vercel /
# Greenhouse — reCAPTCHA Enterprise) and `08053cf9` / `f27fd5ef`
# (Wealthfront / Leverdemo — hCaptcha). These markers appear in script
# tags, iframes, or div ids on every protected page, even when the
# challenge widget hasn't visually rendered yet.
_HCAPTCHA_DOM_MARKERS: tuple[str, ...] = (
    "h-captcha",
    "hcaptcha.com",
    "hcaptcha-enclave",
    "hcaptchasubmitbtn",
    'class="hcaptcha',
    "data-sitekey",  # used together with h-captcha
)
_RECAPTCHA_DOM_MARKERS: tuple[str, ...] = (
    "google_recaptcha_invisible_key",
    "google_recaptcha_endpoint",
    "recaptcha.net/recaptcha/enterprise.js",
    "g-recaptcha",
    "grecaptcha.enterprise",
    "google.com/recaptcha",
)


async def _classify_post_submit_block(page) -> Optional[str]:
    """Inspect post-click DOM for clear captcha/verification scaffolding.

    Returns:
        - 'captcha_required'      → hCaptcha is the blocker (Lever-style)
        - 'verification_required' → reCAPTCHA / reCAPTCHA Enterprise
                                     is the blocker (Greenhouse-style)
        - None                    → no clear marker; caller should fall
                                     through to the generic
                                     `no_confirmation_signal`.

    The hCaptcha check runs first because hCaptcha pages frequently
    ALSO ship reCAPTCHA scaffolding for legacy reasons; whichever is
    actually rendered as the visible widget is what blocks the user,
    and hCaptcha is the more aggressive of the two in practice.

    All checks are case-insensitive substring matches against the full
    DOM. Conservative: a marker must be one of the curated tokens
    above; we don't grep generic words like "captcha" alone (the
    template often references it without enforcement).
    """
    try:
        html = (await page.content()) or ""
    except Exception:
        return None
    low = html.lower()
    if any(m in low for m in _HCAPTCHA_DOM_MARKERS):
        return "captcha_required"
    if any(m in low for m in _RECAPTCHA_DOM_MARKERS):
        return "verification_required"
    return None


async def _detect_confirmation(page, *, url_before: str, settle_timeout_ms: int = 12000) -> tuple[bool, str]:
    """Return (confirmed, reason).

    Conservative — when in doubt, return False with a diagnostic reason.
    Caller can record the reason in submission_log for audit.

    Reason taxonomy (lowest specificity to highest):
        - 'no_confirmation_signal'  : generic miss, no signals at all
        - 'captcha_required'        : hCaptcha gate detected post-click
        - 'verification_required'   : reCAPTCHA gate detected post-click
        - 'url_signal:<token>'      : confirmed via URL path change
        - 'text_signal:"<phrase>"'  : confirmed via body text match

    The captcha/verification reasons let the dashboard surface a
    targeted "verification required, finish in your browser" message
    instead of a generic "no confirmation signal" — same conservative
    behavior (still NOT marked submitted), better diagnostics for the
    user.
    """
    # Let the post-click navigation/XHR settle. networkidle never resolves
    # on long-polling pages, so swallow timeouts and check signals anyway.
    try:
        await page.wait_for_load_state("networkidle", timeout=settle_timeout_ms)
    except Exception:
        pass

    # ── URL change signal ──
    try:
        url_after = (page.url or "")
    except Exception:
        url_after = ""

    if url_after and url_after.lower() != (url_before or "").lower():
        # Strip scheme/host so token matching only sees path + query
        # (avoids matching "complete" inside e.g. "completer.io").
        path_after = url_after.lower()
        scheme_split = path_after.split("://", 1)
        if len(scheme_split) == 2:
            host_and_path = scheme_split[1]
            slash_idx = host_and_path.find("/")
            path_after = host_and_path[slash_idx:] if slash_idx >= 0 else ""
        # Now match tokens against path segments (between slashes/dashes).
        # Whole-segment match keeps false positives down: "/thanks" hits,
        # "/thanksgiving" doesn't.
        segments = [seg for seg in path_after.replace("?", "/").split("/") if seg]
        for seg in segments:
            tokens = seg.replace("-", " ").replace("_", " ").split()
            seg_tokens = set(tokens) | {seg}
            for sig in _CONFIRMATION_URL_TOKENS:
                if sig in seg_tokens:
                    return True, f"url_signal:{sig}"

    # ── Visible text signal ──
    try:
        body_text = (await page.text_content("body")) or ""
    except Exception:
        body_text = ""
    body_lower = body_text.lower()
    for phrase in _CONFIRMATION_TEXT_SIGNALS:
        if phrase in body_lower:
            return True, f"text_signal:{phrase!r}"

    # No confirmation signals. Before falling back to the generic
    # 'no_confirmation_signal', try to identify a captcha/verification
    # wall — that gives the dashboard a precise reason and the user a
    # specific action ("finish in your browser") instead of a vague
    # "no confirmation."
    block_kind = await _classify_post_submit_block(page)
    if block_kind:
        return False, block_kind

    return False, "no_confirmation_signal"


# ─── Submit-button click (try adapter selectors in order) ────────
async def _click_first_match(page, selectors: list[str], *, per_selector_timeout_ms: int = 3500) -> tuple[bool, Optional[str], Optional[str]]:
    """Try each selector in order; click the first one that lands.

    Returns (clicked, selector_used, last_error). Per-selector timeout is
    deliberately short so we can fall through quickly when an adapter's
    primary selector doesn't exist on this particular employer's page.

    Last-resort fallback: if EVERY selector failed but at least one
    actually resolved a DOM element (i.e. the right button was on the
    page but Playwright's actionability check couldn't get past a
    transient overlay or `pointer-events:none` style), retry the FIRST
    resolving selector with `force=True`. This bypasses Playwright's
    visibility/intercept checks. Safe ONLY when the adapter's leading
    selectors are tight (e.g. Lever's `data-qa="btn-submit"`) — never
    use this trick with broad text selectors. Adapters that ship loose
    selectors only get the normal-click path.
    """
    last_err: Optional[str] = None
    first_resolved_sel: Optional[str] = None
    for sel in selectors:
        try:
            await page.click(sel, timeout=per_selector_timeout_ms)
            return True, sel, None
        except Exception as e:
            err_str = str(e)
            last_err = f"{sel} -> {err_str[:140]}"
            # "locator resolved to" appears in Playwright's error message when
            # the selector matched a real element but click couldn't complete
            # (typically: not visible, intercepted, disabled, or unstable).
            # Capture the first such selector for the force-click retry below.
            if first_resolved_sel is None and "locator resolved to" in err_str:
                first_resolved_sel = sel
            continue

    # Force-click fallback. Only the first resolving selector is retried,
    # and only with force=True (which bypasses actionability checks). This
    # rescues the Lever "Submit application" button in cases where a
    # post-fill modal or captcha widget briefly obscures the button — the
    # button is genuinely there and intended to be clicked, Playwright is
    # just being conservative.
    if first_resolved_sel is not None:
        try:
            await page.click(first_resolved_sel, timeout=per_selector_timeout_ms, force=True)
            return True, f"{first_resolved_sel} (force)", None
        except Exception as e:
            last_err = f"{first_resolved_sel} (force) -> {str(e)[:140]}"

    return False, None, last_err


# ─── Main entrypoint ─────────────────────────────────────────────
async def execute_decisions(
    page,
    decisions: list[FieldDecision],
    candidates: list[FieldCandidate],
    *,
    dry_run: bool = False,
    submit_selectors: Optional[list[str]] = None,
) -> ExecutionReport:
    """Walk decisions and apply them. Returns a structured report."""
    cand_by_id = {c.dom_id: c for c in candidates}
    report = ExecutionReport()
    has_review = False

    for dec in decisions:
        cand = cand_by_id.get(dec.dom_id)
        if cand is None:
            report.add(FieldOutcome(dec.dom_id, False, "skip", "no matching candidate"))
            continue

        # SKIP and REVIEW don't interact with DOM (caller decides what to do)
        if dec.source == DecisionSource.SKIP:
            report.add(FieldOutcome(dec.dom_id, True, "skip"))
            continue
        if dec.source == DecisionSource.REVIEW:
            report.add(FieldOutcome(dec.dom_id, True, "review"))
            has_review = True
            continue
        if dec.required_review:
            has_review = True  # still fill it, but block submit

        sel = _primary_selector(cand)
        try:
            if cand.field_type in (FieldType.TEXT, FieldType.EMAIL, FieldType.TEL,
                                    FieldType.URL, FieldType.NUMBER, FieldType.DATE,
                                    FieldType.TEXTAREA):
                await _fill_text(page, sel, dec.value)
                report.add(FieldOutcome(dec.dom_id, True, "fill"))
            elif cand.field_type == FieldType.SELECT:
                await _select(page, sel, str(dec.value))
                report.add(FieldOutcome(dec.dom_id, True, "select"))
            elif cand.field_type == FieldType.RADIO:
                await _check_radio(page, cand, str(dec.value))
                report.add(FieldOutcome(dec.dom_id, True, "select"))
            elif cand.field_type == FieldType.CHECKBOX:
                await _check_checkbox(page, sel, dec.value)
                report.add(FieldOutcome(dec.dom_id, True, "check"))
            elif cand.field_type == FieldType.FILE:
                await _upload(page, sel, str(dec.value))
                report.add(FieldOutcome(dec.dom_id, True, "upload"))
            else:
                report.add(FieldOutcome(dec.dom_id, False, "skip", f"unsupported {cand.field_type}"))
        except Exception as e:
            log.warning("field_fill_failed", extra={"dom_id": dec.dom_id, "err": str(e)})
            report.add(FieldOutcome(dec.dom_id, False, dec.source.value, str(e)[:200]))

    # Submit gate: never submit in dry-run mode; never submit if any required review.
    # `submitted=True` requires post-click confirmation evidence — see
    # _detect_confirmation. A click that doesn't throw is NOT enough.
    if not dry_run and not has_review:
        try:
            url_before = page.url
        except Exception:
            url_before = ""
        # Adapter-provided list takes precedence; fall back to the conservative
        # generic defaults only when no adapter selectors were supplied.
        selectors = submit_selectors if submit_selectors else DEFAULT_SUBMIT_SELECTORS
        clicked, used_sel, last_err = await _click_first_match(page, selectors)
        if not clicked:
            log.warning("submit_failed", extra={"err": last_err})
            report.submitted = False
            report.submit_reason = f"submit_click_failed: no selector matched ({last_err or 'no error'})"
            return report
        confirmed, reason = await _detect_confirmation(page, url_before=url_before)
        report.submitted = confirmed
        # Stitch the matched selector into the reason so audit logs show
        # which Lever/Greenhouse/SR variant landed the click.
        report.submit_reason = f"{reason} via {used_sel}"
        if not confirmed:
            log.warning("submit_unconfirmed", extra={"reason": reason, "selector": used_sel})
    return report


# ─── Sync convenience wrapper ────────────────────────────────────
def execute_decisions_sync(*args, **kwargs) -> ExecutionReport:
    return asyncio.get_event_loop().run_until_complete(execute_decisions(*args, **kwargs))
