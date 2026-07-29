from pathlib import Path

from ingestion.dailymed.dosage_extractor import DosageCandidate, DosageExtractor

GOLDEN_DIR = Path(__file__).parent.parent / "golden" / "dailymed"


def _extract(name: str) -> DosageCandidate:
    xml_bytes = (GOLDEN_DIR / name).read_bytes()
    return DosageExtractor().extract(xml_bytes)


def test_animal_injection_dosage_form() -> None:
    dosage = _extract("animal_injection.xml")
    assert dosage.dosage_form == "INJECTION"
    assert dosage.administration_text is not None


def test_human_rx_injection_dosage_form() -> None:
    dosage = _extract("human_rx_injection.xml")
    assert dosage.dosage_form == "INJECTION"
    assert dosage.administration_text is not None


def test_otc_dosage_form() -> None:
    dosage = _extract("otc_liquid_bandage.xml")
    assert dosage.dosage_form == "LIQUID"


def test_document_with_no_dosage_section_yields_none_administration_text() -> None:
    dosage = _extract("no_ingredients_section.xml")
    assert dosage.dosage_form is None
    assert dosage.administration_text is None
