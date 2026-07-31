from dataclasses import dataclass

from lxml import etree

NS = {"v3": "urn:hl7-org:v3"}

# HL7/FDA SPL's standardized codeSystem OID for DUNS numbers.
DUNS_CODE_SYSTEM = "1.3.6.1.4.1.519.1"

# See ingestion/dailymed/document_metadata.py's _PARSER comment: real SPL
# documents legitimately nest deeper than lxml's default 256-depth guard.
_PARSER = etree.XMLParser(huge_tree=True)


@dataclass(frozen=True)
class ManufacturerCandidate:
    name: str
    duns_number: str | None


class ManufacturerExtractor:
    """Extracts the labeler/manufacturer from an SPL document's header.

    Targets `/document/author/assignedEntity/representedOrganization`
    specifically (an absolute path from the document root) rather than
    `//author` — SPL documents contain other, unrelated `<author>` elements
    deeper in the tree (e.g. a territorialAuthority's author), and matching
    those would silently pick the wrong organization.
    """

    def extract(self, xml_bytes: bytes) -> ManufacturerCandidate | None:
        root = etree.fromstring(xml_bytes, parser=_PARSER)
        orgs = root.xpath(
            "/v3:document/v3:author/v3:assignedEntity/v3:representedOrganization",
            namespaces=NS,
        )
        if not orgs:
            return None

        org = orgs[0]
        names = org.xpath("./v3:name/text()", namespaces=NS)
        if not names:
            return None

        duns_matches = org.xpath(
            "./v3:id[@root=$system]/@extension", namespaces=NS, system=DUNS_CODE_SYSTEM
        )
        return ManufacturerCandidate(
            name=names[0].strip(), duns_number=duns_matches[0] if duns_matches else None
        )
