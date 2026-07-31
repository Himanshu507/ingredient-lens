from dataclasses import dataclass

from lxml import etree

NS = {"v3": "urn:hl7-org:v3"}
INGREDIENTS_SECTION_CODE = "48780-1"

# Real SPL documents' narrative/table sections legitimately nest deeper than
# lxml's default depth guard (256) allows -- that guard exists to protect
# against adversarial XML, not to reject valid government-published labels.
# DailyMed's bulk exports are a trusted, curated source over HTTPS, not
# arbitrary untrusted input, so lifting libxml2's hardening limits here is a
# deliberate, scoped trade-off, not a blanket "disable all XML safety."
_PARSER = etree.XMLParser(huge_tree=True)


@dataclass(frozen=True)
class DocumentMetadata:
    set_id: str
    effective_time: str | None
    version_number: str | None
    product_name: str | None
    product_type: str | None


class DocumentMetadataError(Exception):
    """The document is missing an identifier every valid SPL document has."""


def extract_document_metadata(xml_bytes: bytes) -> DocumentMetadata:
    """Reads document-header identifiers — not a "section" extractor like the
    others, but the same targeted-XPath approach (DAILYMED_INGESTION.md
    Section 5): only the handful of header fields we need, nothing else.
    """
    try:
        root = etree.fromstring(xml_bytes, parser=_PARSER)
    except etree.XMLSyntaxError as exc:
        # A genuinely malformed document is a validation failure like any
        # other -- caught by run.py's `except DocumentMetadataError` and
        # dead-lettered, not left to crash the whole ingestion run.
        raise DocumentMetadataError(f"XML parse failure: {exc}") from exc

    set_ids = root.xpath("/v3:document/v3:setId/@root", namespaces=NS)
    if not set_ids:
        raise DocumentMetadataError("document missing setId")

    effective_times = root.xpath("/v3:document/v3:effectiveTime/@value", namespaces=NS)
    version_numbers = root.xpath("/v3:document/v3:versionNumber/@value", namespaces=NS)
    product_types = root.xpath("/v3:document/v3:code/@displayName", namespaces=NS)
    product_names = root.xpath(
        "//v3:section[v3:code[@code=$code]]"
        "//v3:manufacturedProduct/v3:manufacturedProduct/v3:name/text()",
        namespaces=NS,
        code=INGREDIENTS_SECTION_CODE,
    )

    return DocumentMetadata(
        set_id=set_ids[0],
        effective_time=effective_times[0] if effective_times else None,
        version_number=version_numbers[0] if version_numbers else None,
        product_name=product_names[0].strip() if product_names else None,
        product_type=product_types[0] if product_types else None,
    )
