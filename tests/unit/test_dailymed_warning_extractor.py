from pathlib import Path

from ingestion.dailymed.warning_extractor import WarningCandidate, WarningExtractor

GOLDEN_DIR = Path(__file__).parent.parent / "golden" / "dailymed"


def _extract(name: str) -> list[WarningCandidate]:
    xml_bytes = (GOLDEN_DIR / name).read_bytes()
    return WarningExtractor().extract(xml_bytes)


def test_animal_injection_warnings() -> None:
    """Real record has CONTRAINDICATIONS (34070-3), WARNINGS (34071-1), and
    PRECAUTIONS (42232-9) sections — the latter two both map to our coarser
    "precaution" category."""
    warnings = _extract("animal_injection.xml")

    categories = sorted(w.category for w in warnings)
    assert categories == ["contraindication", "precaution", "precaution"]


def test_human_rx_injection_warnings() -> None:
    """Real record has CONTRAINDICATIONS (34070-3) and the combined WARNINGS
    AND PRECAUTIONS SECTION (43685-7, modern PLR format)."""
    warnings = _extract("human_rx_injection.xml")

    categories = sorted(w.category for w in warnings)
    assert categories == ["contraindication", "precaution"]
    assert any("hypersensitivity" in w.text for w in warnings)


def test_otc_warnings() -> None:
    """Real record has only a WARNINGS SECTION (34071-1)."""
    warnings = _extract("otc_liquid_bandage.xml")

    assert len(warnings) == 1
    assert warnings[0].category == "precaution"


def test_document_with_no_warning_sections_yields_empty_list() -> None:
    warnings = _extract("no_ingredients_section.xml")
    assert warnings == []
