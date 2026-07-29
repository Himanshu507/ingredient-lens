from pathlib import Path

from ingestion.dailymed.manufacturer_extractor import ManufacturerCandidate, ManufacturerExtractor

GOLDEN_DIR = Path(__file__).parent.parent / "golden" / "dailymed"


def _extract(name: str) -> ManufacturerCandidate | None:
    xml_bytes = (GOLDEN_DIR / name).read_bytes()
    return ManufacturerExtractor().extract(xml_bytes)


def test_animal_injection_manufacturer() -> None:
    manufacturer = _extract("animal_injection.xml")
    assert manufacturer is not None
    assert manufacturer.name == "Elanco US Inc."
    assert manufacturer.duns_number == "966985624"


def test_human_rx_injection_manufacturer() -> None:
    manufacturer = _extract("human_rx_injection.xml")
    assert manufacturer is not None
    assert manufacturer.name == "Henry Schein, Inc."
    assert manufacturer.duns_number == "012430880"


def test_otc_manufacturer() -> None:
    manufacturer = _extract("otc_liquid_bandage.xml")
    assert manufacturer is not None
    assert manufacturer.name == "Meijer Distribution Inc"
    assert manufacturer.duns_number == "006959555"


def test_document_with_no_author_returns_none() -> None:
    minimal_doc = b'<document xmlns="urn:hl7-org:v3"/>'
    assert ManufacturerExtractor().extract(minimal_doc) is None
