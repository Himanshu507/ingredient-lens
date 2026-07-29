from lxml import etree

from ingestion.dailymed.models import IngredientCandidate, IngredientRole

NS = {"v3": "urn:hl7-org:v3"}

# LOINC code for the "SPL product data elements section" — the stable
# identifier extractors target, per DAILYMED_INGESTION.md Section 9, rather
# than positional structure ("the third <section> element").
INGREDIENTS_SECTION_CODE = "48780-1"

# HL7/FDA SPL's standardized codeSystem OID for UNII identifiers.
UNII_CODE_SYSTEM = "2.16.840.1.113883.4.9"

# classCode values SPL uses on <ingredient>: ACTIB/ACTIM/ACTIR are variants of
# "active" (basis of strength, moiety, reference), IACT is inactive.
_ACTIVE_CLASS_CODES = {"ACTIB", "ACTIM", "ACTIR"}
_INACTIVE_CLASS_CODES = {"IACT"}


def _role_for_class_code(class_code: str | None) -> IngredientRole | None:
    if class_code in _ACTIVE_CLASS_CODES:
        return "active"
    if class_code in _INACTIVE_CLASS_CODES:
        return "inactive"
    return None


def _first_or_none(values: list[str]) -> str | None:
    return values[0] if values else None


def _text(element: etree._Element, xpath: str) -> str | None:
    return _first_or_none(element.xpath(xpath, namespaces=NS))


def _float(element: etree._Element, xpath: str) -> float | None:
    value = _text(element, xpath)
    return float(value) if value is not None else None


def _unii(ingredient_el: etree._Element) -> str | None:
    matches = ingredient_el.xpath(
        "./v3:ingredientSubstance/v3:code[@codeSystem=$system]/@code",
        namespaces=NS,
        system=UNII_CODE_SYSTEM,
    )
    return _first_or_none(matches)


class IngredientExtractor:
    """Extracts active/inactive ingredients from an SPL document.

    Targets the ingredients section by LOINC code (Section 9), not document
    position, so extraction survives unrelated structural drift between
    documents. A document with no matching section, or one whose ingredient
    elements are missing a name, yields fewer/no candidates rather than
    raising — an absent section is a valid state for some product types
    (Section 9), not an error; that judgment belongs to validation (Brick 9).
    """

    def extract(self, xml_bytes: bytes) -> list[IngredientCandidate]:
        root = etree.fromstring(xml_bytes)
        sections = root.xpath(
            "//v3:section[v3:code[@code=$code]]", namespaces=NS, code=INGREDIENTS_SECTION_CODE
        )

        candidates: list[IngredientCandidate] = []
        for section in sections:
            for ingredient_el in section.xpath(".//v3:ingredient", namespaces=NS):
                role = _role_for_class_code(ingredient_el.get("classCode"))
                if role is None:
                    continue

                name = _text(ingredient_el, "./v3:ingredientSubstance/v3:name/text()")
                if not name:
                    continue

                candidates.append(
                    IngredientCandidate(
                        name=name,
                        role=role,
                        unii=_unii(ingredient_el),
                        quantity_numerator=_float(
                            ingredient_el, "./v3:quantity/v3:numerator/@value"
                        ),
                        quantity_numerator_unit=_text(
                            ingredient_el, "./v3:quantity/v3:numerator/@unit"
                        ),
                        quantity_denominator=_float(
                            ingredient_el, "./v3:quantity/v3:denominator/@value"
                        ),
                        quantity_denominator_unit=_text(
                            ingredient_el, "./v3:quantity/v3:denominator/@unit"
                        ),
                    )
                )
        return candidates
