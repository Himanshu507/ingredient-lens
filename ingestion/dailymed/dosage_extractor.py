from dataclasses import dataclass

from lxml import etree

NS = {"v3": "urn:hl7-org:v3"}

INGREDIENTS_SECTION_CODE = "48780-1"  # SPL product data elements section
DOSAGE_ADMINISTRATION_SECTION_CODE = "34068-7"  # DOSAGE & ADMINISTRATION SECTION


@dataclass(frozen=True)
class DosageCandidate:
    dosage_form: str | None
    administration_text: str | None


class DosageExtractor:
    """Extracts dosage form and administration instructions from an SPL document.

    `dosage_form` comes from `formCode`'s controlled-vocabulary display name
    (e.g. "INJECTION", "TABLET") on the manufactured product itself — a
    structured field, unlike openFDA's free-text label sections (see
    `ingestion/openfda/persistence.py`'s comment on this gap). Administration
    instructions are free text from the dosage/administration section, kept
    separately since it's prose, not a controlled value.
    """

    def extract(self, xml_bytes: bytes) -> DosageCandidate:
        root = etree.fromstring(xml_bytes)

        form_matches = root.xpath(
            "//v3:section[v3:code[@code=$code]]//v3:formCode/@displayName",
            namespaces=NS,
            code=INGREDIENTS_SECTION_CODE,
        )
        dosage_form = form_matches[0] if form_matches else None

        admin_sections = root.xpath(
            "//v3:section[v3:code[@code=$code]]",
            namespaces=NS,
            code=DOSAGE_ADMINISTRATION_SECTION_CODE,
        )
        administration_text = None
        if admin_sections:
            text_nodes = admin_sections[0].xpath("./v3:text//text()", namespaces=NS)
            joined = " ".join(t.strip() for t in text_nodes if t.strip())
            administration_text = joined or None

        return DosageCandidate(dosage_form=dosage_form, administration_text=administration_text)
