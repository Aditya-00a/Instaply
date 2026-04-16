"""Adapter base class and shared parsing helpers.

Every ATS adapter parses raw HTML (from Playwright's page.content())
into a list of FieldCandidate. Adapters never touch Playwright directly —
that's the executor's job. This keeps adapters testable with static HTML.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional, Protocol

from bs4 import BeautifulSoup, Tag

from ..autofill.models import FieldCandidate, FieldType


class AtsKind(str, Enum):
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    SMARTRECRUITERS = "smartrecruiters"
    ASHBY = "ashby"
    WORKDAY = "workday"
    ICIMS = "icims"
    UNKNOWN = "unknown"


class AtsAdapter(Protocol):
    kind: AtsKind

    def detect_url(self, url: str) -> bool: ...
    def detect_html(self, html: str) -> bool: ...
    def parse_form(self, html: str, company_slug: Optional[str] = None) -> list[FieldCandidate]: ...


# ─── Shared parsing helpers ──────────────────────────────────────
_HTML_INPUT_TO_FIELD_TYPE = {
    "text": FieldType.TEXT,
    "email": FieldType.EMAIL,
    "tel": FieldType.TEL,
    "url": FieldType.URL,
    "number": FieldType.NUMBER,
    "date": FieldType.DATE,
    "file": FieldType.FILE,
    "checkbox": FieldType.CHECKBOX,
    "radio": FieldType.RADIO,
    "hidden": FieldType.HIDDEN,
    "password": FieldType.TEXT,  # rare on ATS but treat as text
}


def classify(el: Tag) -> FieldType:
    tag = (el.name or "").lower()
    if tag == "textarea":
        return FieldType.TEXTAREA
    if tag == "select":
        return FieldType.SELECT
    if tag == "input":
        t = (el.get("type") or "text").lower()
        return _HTML_INPUT_TO_FIELD_TYPE.get(t, FieldType.TEXT)
    return FieldType.UNKNOWN


def find_label_for(soup: BeautifulSoup, el: Tag) -> Optional[str]:
    """Return the visible label text for an input.

    Strategy (in order):
      1. aria-labelledby -> text of referenced element(s)
      2. id -> <label for=id>
      3. wrapping <label>
      4. nearest preceding label-ish text (h3/h4/legend/strong/span) in same container
    """
    # 1. aria-labelledby
    aria_ids = (el.get("aria-labelledby") or "").split()
    if aria_ids:
        parts = []
        for aid in aria_ids:
            ref = soup.find(id=aid)
            if ref:
                parts.append(ref.get_text(" ", strip=True))
        if parts:
            return " ".join(parts).strip() or None

    # 2. <label for="id">
    el_id = el.get("id")
    if el_id:
        lbl = soup.find("label", attrs={"for": el_id})
        if lbl:
            return _clean(lbl.get_text(" ", strip=True))

    # 3. wrapping <label>
    wrap = el.find_parent("label")
    if wrap:
        return _clean(wrap.get_text(" ", strip=True))

    # 4. nearest <label> without a `for=` inside same container (Greenhouse's
    #    floating question labels: <label class="question">...</label><select>...)
    for parent in _ancestors(el, max_up=4):
        for lbl in parent.find_all("label"):
            if not lbl.get("for"):
                txt = _clean(lbl.get_text(" ", strip=True))
                if txt:
                    return txt

    # 5. nearest preceding heading/legend/strong within a reasonable container
    for parent in _ancestors(el, max_up=4):
        for sib in parent.find_all(["legend", "h3", "h4", "strong", "span"], recursive=False):
            txt = _clean(sib.get_text(" ", strip=True))
            if txt:
                return txt
    return None


_REQ_MARKERS = "*\u2731\u2605\u2606\u2217\u273d\u29c7"  # * ✱ ★ ☆ ∗ ✽ ⧇


def _clean(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = " ".join(s.split())
    # Strip trailing required-indicator characters (ASCII + common Unicode stars)
    s = s.rstrip(_REQ_MARKERS + " ").strip()
    if s.endswith(" Required"):
        s = s[: -len(" Required")]
    # Also strip any leading/trailing whitespace that surrounded the marker
    return s.strip() or None


def _ancestors(el: Tag, max_up: int = 4):
    cur = el.parent
    n = 0
    while cur is not None and n < max_up:
        yield cur
        cur = cur.parent
        n += 1


def is_required(el: Tag) -> bool:
    if el.has_attr("required"):
        return True
    if (el.get("aria-required") or "").lower() == "true":
        return True
    # Greenhouse marks required via class on wrapper
    for anc in _ancestors(el, max_up=3):
        cls = " ".join(anc.get("class") or [])
        if "required" in cls.lower():
            return True
    return False


def select_options(el: Tag) -> list[str]:
    opts: list[str] = []
    for opt in el.find_all("option"):
        val = _clean(opt.get_text(" ", strip=True))
        if val and val.lower() not in ("select", "please select", "choose", "--"):
            opts.append(val)
    return opts


def radio_options(soup: BeautifulSoup, name: str) -> list[str]:
    """Collect all label texts for radios sharing the same name attr."""
    out: list[str] = []
    for inp in soup.find_all("input", attrs={"type": "radio", "name": name}):
        lbl = find_label_for(soup, inp)
        if lbl:
            out.append(lbl)
        elif inp.get("value"):
            out.append(inp.get("value"))
    # dedupe, preserve order
    seen = set()
    return [x for x in out if not (x in seen or seen.add(x))]
