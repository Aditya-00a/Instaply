"""SmartRecruiters application form adapter.

URLs: jobs.smartrecruiters.com/<company>/<id> or <company>.smartrecruiters.com/...
Apply route often goes through careers.smartrecruiters.com.

DOM conventions:
  - React app renders forms into <form id="applyForm"> or <form data-test="application-form">
  - Field wrappers: <div class="field ...">  with <label>, <input/select/textarea>
  - Many labels use data-test="field-label" attributes
  - Required fields marked via `required` attribute OR `aria-required="true"`
  - Custom questions: under `[data-test="screening-questions"]` section
  - Resume upload uses a custom button that proxies to a hidden file input

SmartRecruiters is noisier than GH/Lever — more dynamic, more ARIA. We lean
heavily on aria-label + data-test attributes.
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
    re.compile(r"smartrecruiters\.com/", re.I),
    re.compile(r"//jobs\.smartrecruiters\.com/", re.I),
    re.compile(r"//careers\.smartrecruiters\.com/", re.I),
]


class SmartRecruitersAdapter:
    kind = AtsKind.SMARTRECRUITERS

    # SmartRecruiters' apply flow lives behind an "I'm interested" call to
    # action; the actual application form's submit is a generic button.
    # Order: most-specific markers, then text fallback, then plain submit.
    submit_selectors: list[str] = [
        "button#i-am-interested",
        "button[type='submit']",
        "button:has-text(\"I'm interested\")",
        "button:has-text('Apply')",
        "button:has-text('Submit application')",
        "button:has-text('Submit')",
    ]

    def detect_url(self, url: str) -> bool:
        return any(p.search(url) for p in _URL_PATTERNS)

    def detect_html(self, html: str) -> bool:
        low = html.lower()
        return (
            "smartrecruiters" in low
            or 'data-test="application-form"' in low
            or 'id="applyform"' in low
            or 'id="apply-form"' in low
        )

    def parse_form(self, html: str, company_slug: Optional[str] = None) -> list[FieldCandidate]:
        soup = BeautifulSoup(html, "lxml")
        form = _find_form(soup)
        if form is None:
            return []

        candidates: list[FieldCandidate] = []
        seen_radio_names: set[str] = set()

        for el in form.find_all(["input", "textarea", "select"]):
            assert isinstance(el, Tag)
            ftype = classify(el)

            if ftype == FieldType.HIDDEN:
                continue
            if (el.get("type") or "").lower() in ("submit", "button", "reset"):
                continue
            if _is_internal(el):
                continue

            if ftype == FieldType.RADIO:
                name = el.get("name") or ""
                if not name or name in seen_radio_names:
                    continue
                seen_radio_names.add(name)
                cand = _radio_candidate(soup, el, name, company_slug)
                if cand:
                    candidates.append(cand)
                continue

            cand = _input_candidate(soup, el, ftype, company_slug)
            if cand:
                candidates.append(cand)

        return candidates


def _find_form(soup: BeautifulSoup) -> Optional[Tag]:
    f = soup.find("form", attrs={"data-test": "application-form"})
    if f:
        return f
    f = soup.find("form", id=re.compile(r"apply[-_]?form", re.I))
    if f:
        return f
    for form in soup.find_all("form"):
        txt = form.get_text(" ", strip=True).lower()
        if "i'm interested" in txt or "submit application" in txt:
            return form
    return soup.find("form")


def _is_internal(el: Tag) -> bool:
    name = (el.get("name") or "").lower()
    el_id = (el.get("id") or "").lower()
    blacklist = ("_token", "csrf", "honeypot", "recaptcha", "authenticity")
    return any(b in name or b in el_id for b in blacklist)


def _find_sr_label(soup: BeautifulSoup, el: Tag) -> Optional[str]:
    # 1. aria-label on the input itself
    aria = el.get("aria-label")
    if aria and aria.strip():
        return aria.strip()
    # 2. standard label resolver (handles aria-labelledby, for=id, wrapping, floating)
    lbl = find_label_for(soup, el)
    if lbl:
        return lbl
    # 3. data-test="field-label" inside the closest .field wrapper
    for anc in _ancestors_up(el, 4):
        lbl_el = anc.find(attrs={"data-test": "field-label"})
        if lbl_el:
            txt = lbl_el.get_text(" ", strip=True)
            if txt:
                return txt.rstrip("*").strip()
    return None


def _ancestors_up(el: Tag, max_up: int):
    cur = el.parent
    n = 0
    while cur is not None and n < max_up:
        yield cur
        cur = cur.parent
        n += 1


def _input_candidate(
    soup: BeautifulSoup, el: Tag, ftype: FieldType, company_slug: Optional[str]
) -> Optional[FieldCandidate]:
    label = _find_sr_label(soup, el)
    name_attr = el.get("name") or ""
    id_attr = el.get("id") or ""
    data_test = el.get("data-test") or ""
    placeholder = el.get("placeholder")
    aria = el.get("aria-label")
    required = is_required(el)
    max_len = _int_or_none(el.get("maxlength"))

    opts: list[str] = []
    if ftype == FieldType.SELECT:
        opts = select_options(el)

    dom_id = id_attr or data_test or name_attr or f"sr_{hash((label, name_attr, ftype)) & 0xFFFFFFFF:x}"

    return FieldCandidate(
        dom_id=dom_id,
        field_type=ftype,
        label=label,
        name_attr=(name_attr or data_test) or None,
        id_attr=id_attr or None,
        placeholder=placeholder,
        aria_label=aria,
        required=required,
        options=opts,
        max_length=max_len,
        company_slug=company_slug,
    )


def _radio_candidate(
    soup: BeautifulSoup, first: Tag, name: str, company_slug: Optional[str]
) -> Optional[FieldCandidate]:
    opts = radio_options(soup, name)
    if not opts:
        return None
    group_label = _find_sr_label(soup, first)
    return FieldCandidate(
        dom_id=f"sr_radio_{name}",
        field_type=FieldType.RADIO,
        label=group_label,
        name_attr=name,
        required=is_required(first),
        options=opts,
        company_slug=company_slug,
    )


def _int_or_none(v):
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None
