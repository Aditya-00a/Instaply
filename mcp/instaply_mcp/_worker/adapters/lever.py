"""Lever application form adapter.

Lever URLs: jobs.lever.co/<company>/<uuid> (posting) — the "Apply" button
navigates to jobs.lever.co/<company>/<uuid>/apply.

DOM conventions (different from Greenhouse):
  - Root form: <form class="application-form" ...>  or  <form id="application-form">
  - Fields wrapped in <li class="application-question"> or <div class="application-field">
  - Labels use <label>, sometimes <div class="application-label"> as a sibling
  - Required fields marked with <span class="required">✱</span> in the label
  - File inputs: <input type="file" name="resume-upload">
  - Custom questions: <div class="application-additional"> grouping
  - `data-qa` attributes on many elements — useful fallback identifier
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
    re.compile(r"jobs\.lever\.co/", re.I),
    re.compile(r"//[^/]*\.lever\.co/", re.I),
]


class LeverAdapter:
    kind = AtsKind.LEVER

    # Lever's real submit button has these stable markers:
    #   <button id="btn-submit" type="button"
    #           class="postings-btn template-btn-submit shamrock"
    #           data-qa="btn-submit" href="#">Submit application</button>
    # CRITICAL: type="button" — NOT type="submit". The page ALSO contains
    #   <button id="hcaptchaSubmitBtn" type="submit" class="hidden">…
    # which is the hCaptcha integration's hidden helper. A bare
    # `button[type='submit']` selector matches THAT hidden button first,
    # times out clicking it (it's `.hidden`), and burns the per-selector
    # budget — that was the root cause of the 2026-04-18 f27fd5ef
    # `submit_click_failed` after the agent answered every question.
    # Strategy: lead with Lever's stable identifiers (`data-qa` first,
    # then `#id`, then the unique class combo). Exclude `.hidden`
    # everywhere so we never sink time into the captcha helper. Drop
    # the bare `button[type='submit']` for Lever specifically (kept in
    # DEFAULT_SUBMIT_SELECTORS for other ATSes that genuinely use it).
    submit_selectors: list[str] = [
        "button[data-qa='btn-submit']:not(.hidden)",
        "button#btn-submit:not(.hidden)",
        "button.template-btn-submit:not(.hidden)",
        "button.postings-btn:has-text('Submit application'):not(.hidden)",
        "button.postings-btn:has-text('Submit'):not(.hidden)",
        "button:has-text('Submit application'):not(.hidden)",
    ]

    def detect_url(self, url: str) -> bool:
        return any(p.search(url) for p in _URL_PATTERNS)

    def detect_html(self, html: str) -> bool:
        low = html.lower()
        return (
            "lever.co" in low
            or "application-form" in low and "posting-headline" in low
            or "data-qa=\"application-form\"" in low
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
    f = soup.find("form", attrs={"data-qa": "application-form"})
    if f:
        return f
    f = soup.find("form", class_=lambda c: c and "application-form" in c)
    if f:
        return f
    f = soup.find("form", id=re.compile(r"application[-_]?form", re.I))
    if f:
        return f
    # Fallback: form containing a "Submit application" button
    for form in soup.find_all("form"):
        txt = form.get_text(" ", strip=True).lower()
        if "submit application" in txt or "submit my application" in txt:
            return form
    return soup.find("form")


def _is_internal(el: Tag) -> bool:
    name = (el.get("name") or "").lower()
    el_id = (el.get("id") or "").lower()
    blacklist = ("authenticity_token", "utf8", "_csrf", "honeypot", "recaptcha")
    return any(b in name or b in el_id for b in blacklist)


def _find_lever_label(soup: BeautifulSoup, el: Tag) -> Optional[str]:
    """Lever sometimes puts labels in .application-label siblings instead of <label>.

    Walks up to 8 ancestors (was 4) — Lever's EEO and survey blocks bury
    the .application-label one level deeper than custom-question blocks,
    and the previous limit caused fields like `eeo[race]` and the
    surveys radio groups to fall through to their raw `name` attribute
    (e.g. "eeo[race]") in needs_review, which is unreadable for testers.
    Prefer the inner .application-label specifically — falling back to
    the broader .application-question container surfaces the entire
    question + all options jammed together.
    """
    # Standard label resolver first
    lbl = find_label_for(soup, el)
    if lbl:
        return lbl
    # Look for a .application-label inside any reasonable ancestor.
    for anc in _ancestors_up(el, 8):
        lbl_div = anc.find(class_=re.compile(r"application[-_]?label", re.I))
        if lbl_div:
            txt = lbl_div.get_text(" ", strip=True)
            if txt and len(txt) < 400:
                return txt.strip().rstrip("*").strip()
    # Last-resort: a generic question/posting-requirements container.
    for anc in _ancestors_up(el, 8):
        lbl_div = anc.find(class_=re.compile(r"\bquestion\b|posting-requirements", re.I))
        if lbl_div:
            txt = lbl_div.get_text(" ", strip=True)
            if txt and len(txt) < 400:
                return txt.strip().rstrip("*").strip()
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
    label = _find_lever_label(soup, el)
    name_attr = el.get("name") or ""
    id_attr = el.get("id") or ""
    placeholder = el.get("placeholder")
    aria = el.get("aria-label")
    data_qa = el.get("data-qa")
    required = is_required(el)
    max_len = _int_or_none(el.get("maxlength"))

    opts: list[str] = []
    if ftype == FieldType.SELECT:
        opts = select_options(el)

    dom_id = id_attr or data_qa or name_attr or f"lv_{hash((label, name_attr, ftype)) & 0xFFFFFFFF:x}"

    # Use data-qa as a name hint if name is missing — Lever often uses it
    name_for_rules = name_attr or data_qa or ""

    return FieldCandidate(
        dom_id=dom_id,
        field_type=ftype,
        label=label,
        name_attr=name_for_rules or None,
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
    group_label = _find_radio_group_label(first)
    return FieldCandidate(
        dom_id=f"lv_radio_{name}",
        field_type=FieldType.RADIO,
        label=group_label,
        name_attr=name,
        required=is_required(first),
        options=opts,
        company_slug=company_slug,
    )


def _find_radio_group_label(el: Tag) -> Optional[str]:
    """Resolve a Lever radio group's question text.

    Walks up to 8 ancestors (was 4). For Lever EEO/survey radio groups
    the question label sits inside a .application-question wrapper one
    level deeper than the radio button itself — the previous max_up=4
    missed it, leaking the raw name attr (e.g. "eeo[race]") into
    needs_review. Prefer the inner .application-label specifically; the
    bare ".question" class on the outer wrapper concatenates the whole
    block of options when extracted.
    """
    fs = el.find_parent("fieldset")
    if fs:
        leg = fs.find("legend")
        if leg:
            txt = leg.get_text(" ", strip=True)
            if txt:
                return txt
    # Inside any .application-question ancestor, find the .application-label.
    for anc in _ancestors_up(el, 8):
        cls = anc.get("class") or []
        if isinstance(cls, str):
            cls = [cls]
        if any("application-question" in c for c in cls):
            lbl = anc.find(class_=re.compile(r"application[-_]?label", re.I))
            if lbl:
                txt = lbl.get_text(" ", strip=True)
                if txt and len(txt) < 400:
                    return txt.strip().rstrip("*").strip()
    # Fallback: any .application-label within 8 ancestors.
    for anc in _ancestors_up(el, 8):
        lbl = anc.find(class_=re.compile(r"application[-_]?label", re.I))
        if lbl:
            txt = lbl.get_text(" ", strip=True)
            if txt and len(txt) < 400:
                return txt.strip().rstrip("*").strip()
    return None


def _int_or_none(v) -> Optional[int]:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None
