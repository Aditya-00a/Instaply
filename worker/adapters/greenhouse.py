"""Greenhouse application form adapter.

Greenhouse is the cleanest ATS to parse:
  - URLs look like boards.greenhouse.io/<company>/jobs/<id> OR
    <company>.greenhouse.io/jobs/<id>
  - Forms use standard <label for="..."> patterns
  - `.field` div wraps each field; `.required` class marks required ones
  - Custom questions live under `#custom_questions`
  - EEO section is `#eeo_fields` (may be hidden/collapsed)

We walk <input>, <textarea>, <select> under the application form and emit
FieldCandidates. Radio groups are collapsed to a single candidate whose
options list the radio labels.
"""
from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup, Tag

from ..autofill.models import FieldCandidate, FieldType
from .base import (
    AtsKind,
    classify,
    find_label_for,
    is_required,
    radio_options,
    select_options,
)


_URL_PATTERNS = [
    re.compile(r"boards\.greenhouse\.io/", re.I),
    re.compile(r"\.greenhouse\.io/", re.I),
    re.compile(r"boards\.eu\.greenhouse\.io/", re.I),
    re.compile(r"job-boards\.greenhouse\.io/", re.I),
]


class GreenhouseAdapter:
    kind = AtsKind.GREENHOUSE

    # ── Detection ──────────────────────────────────────────────
    def detect_url(self, url: str) -> bool:
        return any(p.search(url) for p in _URL_PATTERNS)

    def detect_html(self, html: str) -> bool:
        low = html.lower()
        return (
            "greenhouse.io" in low
            or 'id="application_form"' in low
            or 'id="application-form"' in low
            or "grnhse_iframe" in low
        )

    # ── Parse ──────────────────────────────────────────────────
    def parse_form(self, html: str, company_slug: Optional[str] = None) -> list[FieldCandidate]:
        soup = BeautifulSoup(html, "lxml")
        form = _find_application_form(soup)
        if form is None:
            return []

        candidates: list[FieldCandidate] = []
        seen_radio_names: set[str] = set()

        # Walk every fillable input
        for el in form.find_all(["input", "textarea", "select"]):
            assert isinstance(el, Tag)
            ftype = classify(el)

            # Skip submit buttons, hidden tokens, and pre-filled hidden trackers
            if ftype == FieldType.HIDDEN:
                continue
            if (el.get("type") or "").lower() in ("submit", "button", "reset"):
                continue
            if _looks_like_internal_token(el):
                continue

            # Radio groups: collapse to one candidate per name attr
            if ftype == FieldType.RADIO:
                name = el.get("name") or ""
                if not name or name in seen_radio_names:
                    continue
                seen_radio_names.add(name)
                cand = _radio_to_candidate(soup, el, name, company_slug)
                if cand:
                    candidates.append(cand)
                continue

            cand = _input_to_candidate(soup, el, ftype, company_slug)
            if cand:
                candidates.append(cand)

        return candidates


# ─── Internals ──────────────────────────────────────────────────
def _find_application_form(soup: BeautifulSoup) -> Optional[Tag]:
    # Most Greenhouse boards
    f = soup.find("form", id=["application_form", "application-form"])
    if f:
        return f
    # Some variants use an id on the wrapping div
    wrap = soup.find(id=["application", "application-form"])
    if wrap:
        f = wrap.find("form")
        if f:
            return f
    # Fallback: any form containing a "Submit Application" button
    for form in soup.find_all("form"):
        txt = form.get_text(" ", strip=True).lower()
        if "submit application" in txt or "apply for this job" in txt:
            return form
    return soup.find("form")  # last resort


def _looks_like_internal_token(el: Tag) -> bool:
    name = (el.get("name") or "").lower()
    el_id = (el.get("id") or "").lower()
    blacklist = (
        "authenticity_token",
        "utf8",
        "_token",
        "csrf",
        "honeypot",
        "recaptcha",
        "g-recaptcha",
    )
    return any(b in name or b in el_id for b in blacklist)


def _input_to_candidate(
    soup: BeautifulSoup, el: Tag, ftype: FieldType, company_slug: Optional[str]
) -> Optional[FieldCandidate]:
    label = find_label_for(soup, el)
    name_attr = el.get("name") or ""
    id_attr = el.get("id") or ""
    placeholder = el.get("placeholder")
    aria = el.get("aria-label")
    required = is_required(el)
    max_len = _int_or_none(el.get("maxlength"))

    opts: list[str] = []
    if ftype == FieldType.SELECT:
        opts = select_options(el)

    dom_id = id_attr or name_attr or f"gh_{hash((label, name_attr, ftype)) & 0xFFFFFFFF:x}"

    return FieldCandidate(
        dom_id=dom_id,
        field_type=ftype,
        label=label,
        name_attr=name_attr or None,
        id_attr=id_attr or None,
        placeholder=placeholder,
        aria_label=aria,
        required=required,
        options=opts,
        max_length=max_len,
        company_slug=company_slug,
    )


def _radio_to_candidate(
    soup: BeautifulSoup, first: Tag, name: str, company_slug: Optional[str]
) -> Optional[FieldCandidate]:
    opts = radio_options(soup, name)
    if not opts:
        return None
    # Try to find the group's question label: often a legend or preceding span
    group_label = _find_radio_group_label(first)
    dom_id = f"gh_radio_{name}"
    # Required if any radio in the group is required or group wrapper is .required
    required = is_required(first)
    return FieldCandidate(
        dom_id=dom_id,
        field_type=FieldType.RADIO,
        label=group_label,
        name_attr=name,
        id_attr=None,
        required=required,
        options=opts,
        company_slug=company_slug,
    )


def _find_radio_group_label(el: Tag) -> Optional[str]:
    # Walk up looking for a fieldset legend, then h3/h4/strong/span containing text
    fs = el.find_parent("fieldset")
    if fs:
        leg = fs.find("legend")
        if leg:
            txt = leg.get_text(" ", strip=True)
            if txt:
                return txt
    # GH often uses a <label class="question"> above the radios
    cur = el
    for _ in range(4):
        cur = cur.parent
        if cur is None:
            break
        for tag_name in ("legend", "label", "h3", "h4", "strong"):
            sib = cur.find(tag_name)
            if sib:
                txt = sib.get_text(" ", strip=True)
                if txt and len(txt) < 300:
                    return txt
    return None


def _int_or_none(v) -> Optional[int]:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None
