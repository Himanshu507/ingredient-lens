from pathlib import Path

from ingestion.dailymed.ingredient_extractor import IngredientExtractor
from ingestion.dailymed.models import IngredientCandidate

GOLDEN_DIR = Path(__file__).parent / "dailymed"


def _extract(name: str) -> list[IngredientCandidate]:
    xml_bytes = (GOLDEN_DIR / name).read_bytes()
    return IngredientExtractor().extract(xml_bytes)


def test_animal_injection_single_active_ingredient() -> None:
    """Real record: Micotil 300 (animal drug), one active ingredient, no
    inactive ingredients, classCode="ACTIB"."""
    candidates = _extract("animal_injection.xml")

    assert len(candidates) == 1
    ingredient = candidates[0]
    assert ingredient.name == "tilmicosin phosphate"
    assert ingredient.role == "active"
    assert ingredient.unii == "SMH7U1S683"
    assert ingredient.quantity_numerator == 300
    assert ingredient.quantity_numerator_unit == "mg"
    assert ingredient.quantity_denominator == 1
    assert ingredient.quantity_denominator_unit == "mL"


def test_human_rx_injection_active_moiety_and_inactives_without_quantity() -> None:
    """Real record: Ondansetron Injection — classCode="ACTIM" for the active
    ingredient, four classCode="IACT" inactive ingredients with no <quantity>
    element at all (a legitimately absent optional element, not an error)."""
    candidates = _extract("human_rx_injection.xml")

    assert len(candidates) == 5
    by_name = {c.name: c for c in candidates}

    active = by_name["ONDANSETRON HYDROCHLORIDE"]
    assert active.role == "active"
    assert active.unii == "NMH84OZK2B"
    assert active.quantity_numerator == 2
    assert active.quantity_numerator_unit == "mg"

    inactive_names = {
        "SODIUM CHLORIDE",
        "CITRIC ACID MONOHYDRATE",
        "TRISODIUM CITRATE DIHYDRATE",
        "WATER",
    }
    for name in inactive_names:
        ingredient = by_name[name]
        assert ingredient.role == "inactive"
        assert ingredient.quantity_numerator is None
        assert ingredient.quantity_denominator is None


def test_otc_multi_active_ingredient_product() -> None:
    """Real record: Meijer Liquid Bandage — two active ingredients
    (classCode="ACTIB"), six inactive."""
    candidates = _extract("otc_liquid_bandage.xml")

    assert len(candidates) == 8
    roles = [c.role for c in candidates]
    assert roles.count("active") == 2
    assert roles.count("inactive") == 6

    by_name = {c.name: c for c in candidates}
    assert by_name["BENZETHONIUM CHLORIDE"].role == "active"
    assert by_name["BENZETHONIUM CHLORIDE"].quantity_numerator == 2
    assert by_name["DYCLONINE HYDROCHLORIDE"].quantity_numerator == 7.5


def test_document_with_no_ingredients_section_yields_empty_list() -> None:
    """Synthetic, hand-built fixture (no real document omits this section in
    our sample set) — an absent ingredients section is a valid state for
    some product types (DAILYMED_INGESTION.md Section 9), not an error."""
    candidates = _extract("no_ingredients_section.xml")

    assert candidates == []
