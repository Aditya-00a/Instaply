import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from instaply.actions import _primary_selector
from instaply.autofill.models import FieldCandidate, FieldType


def test_checkbox_primary_selector_targets_checkbox_input_not_hidden_sibling():
    cand = FieldCandidate(
        dom_id="consent[marketing]",
        field_type=FieldType.CHECKBOX,
        label="Consent",
        name_attr="consent[marketing]",
        id_attr=None,
        required=False,
    )

    selector = _primary_selector(cand)

    assert selector == 'input[type="checkbox"][name="consent[marketing]"]'
