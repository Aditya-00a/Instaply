"""ATS-specific DOM adapters.

Each adapter walks the application form DOM of one ATS and emits a
list of FieldCandidate. The autofill engine is entirely ATS-agnostic
past this point — it just sees structured field descriptors.

Adapter registry: given a URL or HTML, pick the right adapter.
"""
from __future__ import annotations

from typing import Optional

from .base import AtsAdapter, AtsKind
from .greenhouse import GreenhouseAdapter
from .lever import LeverAdapter
from .smartrecruiters import SmartRecruitersAdapter

_ADAPTERS: list[AtsAdapter] = [
    GreenhouseAdapter(),
    LeverAdapter(),
    SmartRecruitersAdapter(),
]


def adapter_for_url(url: str) -> Optional[AtsAdapter]:
    for a in _ADAPTERS:
        if a.detect_url(url):
            return a
    return None


def adapter_for_html(html: str, url: Optional[str] = None) -> Optional[AtsAdapter]:
    if url:
        hit = adapter_for_url(url)
        if hit:
            return hit
    for a in _ADAPTERS:
        if a.detect_html(html):
            return a
    return None


__all__ = ["AtsAdapter", "AtsKind", "adapter_for_url", "adapter_for_html"]
