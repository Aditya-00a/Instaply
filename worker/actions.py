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


# ─── Main entrypoint ─────────────────────────────────────────────
async def execute_decisions(
    page,
    decisions: list[FieldDecision],
    candidates: list[FieldCandidate],
    *,
    dry_run: bool = False,
    submit_selector: str = 'button[type="submit"], input[type="submit"]',
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

    # Submit gate: never submit in dry-run mode; never submit if any required review
    if not dry_run and not has_review:
        try:
            await page.click(submit_selector, timeout=8000)
            report.submitted = True
        except Exception as e:
            log.warning("submit_failed", extra={"err": str(e)})
            report.submitted = False
    return report


# ─── Sync convenience wrapper ────────────────────────────────────
def execute_decisions_sync(*args, **kwargs) -> ExecutionReport:
    return asyncio.get_event_loop().run_until_complete(execute_decisions(*args, **kwargs))
