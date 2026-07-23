from unittest.mock import patch

from api import match
from db.models import Ingredient, IngredientRegulatoryStatus


def _seed(session, name: str, synonyms: list[str], status: str, confidence: float = 0.9):
    ingredient = Ingredient(name=name, synonyms=synonyms)
    session.add(ingredient)
    session.flush()
    session.add(
        IngredientRegulatoryStatus(
            ingredient_id=ingredient.id,
            country_id="US",
            normalized_status=status,
            category_codes=[3],
            reasoning="test reasoning",
            confidence=confidence,
            needs_review=confidence < 0.7,
            citation_url="https://www.fda.gov/example",
            citation_text="Safety Communication",
            date_added="2023/04",
        )
    )
    session.commit()
    return ingredient


def test_split_candidates_handles_lines_and_commas():
    assert match.split_candidates("DMAA\nVitamin C, Cocoa Powder") == [
        "DMAA",
        "Vitamin C",
        "Cocoa Powder",
    ]


def test_split_candidates_drops_empties_and_whitespace():
    assert match.split_candidates("DMAA,, \n \n Vitamin C") == ["DMAA", "Vitamin C"]


def test_split_candidates_keeps_commas_inside_parens_as_one_entry():
    text = "Cocoa Powder, Artificial Flavours (Chocolate, Vanilla), Sweetener INS 950"
    assert match.split_candidates(text) == [
        "Cocoa Powder",
        "Artificial Flavours (Chocolate, Vanilla)",
        "Sweetener INS 950",
    ]


def test_exact_match_is_case_insensitive(db_session):
    _seed(db_session, "DMAA", ["1,4-dimethylamylamine"], "not_a_dietary_ingredient")

    with patch.object(match, "_llm_match", return_value=None) as llm:
        results = match.check_ingredients("dmaa", db_session)

    assert results[0].matched_ingredient == "DMAA"
    assert results[0].status == "not_a_dietary_ingredient"
    assert results[0].citation == "https://www.fda.gov/example"
    llm.assert_not_called()  # exact match found -- never reaches LLM tier


def test_synonym_match(db_session):
    # note: a synonym containing a literal comma (e.g. "1,4-dimethylamylamine")
    # would itself get split by the comma-separated candidate splitter -- a
    # real ambiguity in free-text input, not something this test should mask.
    _seed(db_session, "DMAA", ["dimethylamylamine"], "not_a_dietary_ingredient")

    with patch.object(match, "_llm_match", return_value=None) as llm:
        results = match.check_ingredients("dimethylamylamine", db_session)

    assert results[0].matched_ingredient == "DMAA"
    llm.assert_not_called()


def test_fuzzy_match_on_near_miss_spelling(db_session):
    _seed(db_session, "Ephedra Sinica", [], "excluded_from_definition")

    with patch.object(match, "_llm_match", return_value=None) as llm:
        results = match.check_ingredients("Ephedra Sinca", db_session)  # OCR-style typo

    assert results[0].matched_ingredient == "Ephedra Sinica"
    llm.assert_not_called()  # fuzzy tier resolved it, no need for LLM


def test_unmatched_candidate_falls_through_to_llm_then_not_in_database(db_session):
    _seed(db_session, "DMAA", [], "not_a_dietary_ingredient")

    with patch.object(match, "_llm_match", return_value=None) as llm:
        results = match.check_ingredients("Completely Unrelated Thing", db_session)

    assert results[0].status == "not_in_database"
    assert results[0].matched_ingredient is None
    llm.assert_called_once()  # only reached as last resort after exact/synonym/fuzzy fail


def test_llm_outage_degrades_to_not_in_database_instead_of_crashing(db_session):
    _seed(db_session, "DMAA", [], "not_a_dietary_ingredient")

    with patch.object(match, "_get_client", side_effect=RuntimeError("network down")):
        results = match.check_ingredients("Something Novel", db_session)

    assert results[0].status == "not_in_database"


def test_build_summary_counts_each_bucket():
    results = [
        match.IngredientCheckResult(
            submitted_name="a", matched_ingredient="a", status="permitted_with_claim",
            reasoning=None, citation=None, confidence=0.9,
        ),
        match.IngredientCheckResult(
            submitted_name="b", matched_ingredient="b", status="not_a_dietary_ingredient",
            reasoning=None, citation=None, confidence=0.9,
        ),
        match.IngredientCheckResult(
            submitted_name="c", matched_ingredient=None, status="not_in_database",
            reasoning=None, citation=None, confidence=None,
        ),
    ]
    assert match.build_summary(results) == "1 flagged, 1 clear, 1 not FDA-flagged"
