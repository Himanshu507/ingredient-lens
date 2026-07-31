from pathlib import Path

import pytest

from ingestion.dailymed.document_metadata import DocumentMetadataError, extract_document_metadata

GOLDEN_DIR = Path(__file__).parent.parent / "golden" / "dailymed"


def _load(name: str) -> bytes:
    return (GOLDEN_DIR / name).read_bytes()


def test_animal_injection_metadata() -> None:
    metadata = extract_document_metadata(_load("animal_injection.xml"))

    assert metadata.set_id == "08f1aecd-33c2-457b-8a45-c38fafb3a1c7"
    assert metadata.effective_time == "20260722"
    assert metadata.version_number == "8"
    assert metadata.product_name == "Micotil 300"
    assert metadata.product_type == "PRESCRIPTION ANIMAL DRUG LABEL"


def test_human_rx_injection_metadata() -> None:
    metadata = extract_document_metadata(_load("human_rx_injection.xml"))

    assert metadata.set_id == "1a44601b-c31c-4779-a688-28cc4cc75e8b"
    assert metadata.version_number == "8"
    assert metadata.product_name == "ONDANSETRON"
    assert metadata.product_type == "HUMAN PRESCRIPTION DRUG LABEL"


def test_document_missing_set_id_raises() -> None:
    minimal_doc = b'<document xmlns="urn:hl7-org:v3"><code displayName="X"/></document>'
    with pytest.raises(DocumentMetadataError):
        extract_document_metadata(minimal_doc)


def test_deeply_nested_document_parses_without_crashing() -> None:
    """Real SPL narrative/table sections can legitimately nest past lxml's
    default 256-element depth guard -- a document this deep must still parse,
    not raise XMLSyntaxError (this reproduces a real crash hit while bulk-
    ingesting DailyMed's human_rx full release)."""
    depth = 300
    nested = ("<a>" * depth) + "text" + ("</a>" * depth)
    doc = (
        b'<document xmlns="urn:hl7-org:v3">'
        b'<setId root="11111111-1111-1111-1111-111111111111"/>' + nested.encode() + b"</document>"
    )

    metadata = extract_document_metadata(doc)

    assert metadata.set_id == "11111111-1111-1111-1111-111111111111"


def test_malformed_xml_raises_document_metadata_error_not_raw_syntax_error() -> None:
    """A genuine parse failure must come out as DocumentMetadataError so
    ingestion/dailymed/run.py's existing except clause dead-letters just this
    document -- an uncaught lxml.etree.XMLSyntaxError would crash the whole
    ingestion run instead."""
    malformed = b"<document xmlns='urn:hl7-org:v3'><setId root='x'/>"  # unclosed tag
    with pytest.raises(DocumentMetadataError):
        extract_document_metadata(malformed)
