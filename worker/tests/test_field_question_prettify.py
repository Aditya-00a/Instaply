"""Smoke tests for `field_question` prettification.

When the upstream label resolver fails (Lever's deeper EEO/survey
blocks, or dynamically-rendered card containers), `field_question`
falls through to the raw `name` attr. Without prettification the
dashboard renders `eeo[race]`, `cards[uuid][field0]`, and
`surveysResponses[uuid][responses][field1]` verbatim — unreadable to a
tester.

The prettifier ONLY runs when there is no real label/aria/placeholder
to use. A real label (e.g. "Race") is preserved unchanged so we never
mangle good upstream data.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from worker.autofill.cache import field_question
from worker.autofill.models import FieldCandidate, FieldType


def _bare(name: str, *, label: str | None = None, ftype: FieldType = FieldType.TEXT) -> FieldCandidate:
    return FieldCandidate(dom_id=f"d_{name}", field_type=ftype, label=label, name_attr=name)


def test_real_label_is_never_prettified():
    cand = _bare("eeo[race]", label="Race")
    assert field_question(cand) == "Race"


def test_eeo_race_raw_name_becomes_human_readable():
    cand = _bare("eeo[race]")
    assert field_question(cand) == "Race (EEO)"


def test_eeo_camelcase_token_is_humanized():
    cand = _bare("eeo[disabilitySignatureDate]")
    assert field_question(cand) == "Disability Signature Date (EEO)"


def test_lever_custom_card_field_zero_indexed():
    cand = _bare("cards[a1d93a51-fdfb-40d0-88bc-10dabbf56636][field0]")
    assert field_question(cand) == "Custom question 1"


def test_lever_custom_card_field_seven_indexed():
    cand = _bare("cards[a1d93a51-fdfb-40d0-88bc-10dabbf56636][field7]")
    assert field_question(cand) == "Custom question 8"


def test_lever_survey_response_field_one_indexed():
    cand = _bare("surveysResponses[8dfb36ea-fd79-4bea-aa2d-734a7b290c35][responses][field1]")
    assert field_question(cand) == "Survey question 2"


def test_lv_radio_wrapper_unwraps_then_prettifies():
    """`dom_id`-style names sometimes leak as `lv_radio_<inner>` (the
    Lever adapter prefixes the dom_id but the prettifier sees them when
    name_attr is missing). Make sure we re-pass through the inner name.
    """
    cand = FieldCandidate(
        dom_id="lv_radio_eeo[race]",
        field_type=FieldType.RADIO,
        name_attr=None,
        id_attr=None,
        label=None,
    )
    # name_attr is None so field_question falls through to id_attr/dom_id.
    # dom_id "lv_radio_eeo[race]" should become "Race (EEO)".
    assert field_question(cand) == "Race (EEO)"


def test_unknown_raw_name_passes_through():
    cand = _bare("totally_random_field_name")
    # No pattern matches — the prettifier returns the input unchanged.
    assert field_question(cand) == "totally_random_field_name"
