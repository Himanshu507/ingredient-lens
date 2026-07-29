import json
from pathlib import Path
from typing import Any

from ingestion.openfda.parser import parse_drug_label_record

GOLDEN_DIR = Path(__file__).parent / "openfda"


def _load(name: str) -> dict[str, Any]:
    with (GOLDEN_DIR / name).open() as f:
        result: dict[str, Any] = json.load(f)
        return result


def test_parses_otc_record_with_active_ingredient_and_warnings() -> None:
    """Real openFDA record: OTC homeopathic product with `set_id`, `active_ingredient`,
    and a top-level `warnings` section — the "simple" shape."""
    raw = _load("drug_label_otc.json")

    parsed = parse_drug_label_record(raw)

    assert parsed.set_id == "0000025c-6dbf-4af7-a741-5cbacaed519a"
    assert parsed.brand_name == "SILICEA"
    assert parsed.generic_name == "SILICEA"
    assert parsed.manufacturer_name == "Rxhomeo Private Limited d.b.a. Rxhomeo, Inc"
    assert parsed.substance_name == ("SILICON DIOXIDE",)
    assert parsed.product_type == "HUMAN OTC DRUG"
    assert parsed.route == ("ORAL",)
    assert parsed.active_ingredient_text == ("ACTIVE INGREDIENT SILICEA HPUS 2X and higher",)
    assert len(parsed.warnings_text) == 1
    assert parsed.boxed_warning_text == ()


def test_parses_prescription_record_with_boxed_warning_and_no_active_ingredient() -> None:
    """Real openFDA record: prescription drug with a `boxed_warning` section and
    *no* top-level `active_ingredient`/`warnings` fields at all — the "optional
    sections absent" shape that golden files exist to catch (TESTING_STRATEGY.md §4)."""
    raw = _load("drug_label_boxed_warning.json")

    parsed = parse_drug_label_record(raw)

    assert parsed.brand_name == "Naproxen"
    assert parsed.manufacturer_name == "A-S Medication Solutions"
    assert parsed.substance_name == ("NAPROXEN",)
    assert parsed.product_type == "HUMAN PRESCRIPTION DRUG"
    assert parsed.route == ("ORAL",)
    assert len(parsed.boxed_warning_text) >= 1
    assert parsed.active_ingredient_text == ()
    assert parsed.warnings_text == ()
