from dataclasses import dataclass
from typing import Literal

from lxml import etree

NS = {"v3": "urn:hl7-org:v3"}

WarningCategoryLiteral = Literal["boxed_warning", "contraindication", "precaution"]

# Section LOINC codes mapped to our (coarser) canonical WarningCategory —
# SPL distinguishes several warning-adjacent section types; our canonical
# model buckets them into three categories (DATABASE_DESIGN.md). Targeting
# by LOINC code, not document position, per DAILYMED_INGESTION.md Section 9.
_WARNING_SECTION_CODES: dict[str, WarningCategoryLiteral] = {
    "34066-1": "boxed_warning",  # BOXED WARNING SECTION
    "34070-3": "contraindication",  # CONTRAINDICATIONS SECTION
    "34071-1": "precaution",  # WARNINGS SECTION
    "42232-9": "precaution",  # PRECAUTIONS SECTION
    "43685-7": "precaution",  # WARNINGS AND PRECAUTIONS SECTION (combined, PLR-format labels)
}


@dataclass(frozen=True)
class WarningCandidate:
    category: WarningCategoryLiteral
    text: str


def _section_text(section: etree._Element) -> str | None:
    text_nodes = section.xpath("./v3:text//text()", namespaces=NS)
    joined = " ".join(t.strip() for t in text_nodes if t.strip())
    return joined or None


class WarningExtractor:
    """Extracts warning-adjacent sections from an SPL document.

    A document missing some or all of these sections (e.g. no boxed warning)
    is a valid, common state — not an error (DAILYMED_INGESTION.md Section 9).
    """

    def extract(self, xml_bytes: bytes) -> list[WarningCandidate]:
        root = etree.fromstring(xml_bytes)
        candidates: list[WarningCandidate] = []

        for code, category in _WARNING_SECTION_CODES.items():
            sections = root.xpath("//v3:section[v3:code[@code=$code]]", namespaces=NS, code=code)
            for section in sections:
                text = _section_text(section)
                if text:
                    candidates.append(WarningCandidate(category=category, text=text))

        return candidates
