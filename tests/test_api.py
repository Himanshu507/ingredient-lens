from unittest.mock import patch

from fastapi.testclient import TestClient

from api import match
from api.main import app
from db.models import Ingredient, IngredientRegulatoryStatus

client = TestClient(app)


def _seed(session, name: str, status: str):
    ingredient = Ingredient(name=name, synonyms=[])
    session.add(ingredient)
    session.flush()
    session.add(
        IngredientRegulatoryStatus(
            ingredient_id=ingredient.id,
            country_id="US",
            normalized_status=status,
            category_codes=[3],
            reasoning="test reasoning",
            confidence=0.9,
            needs_review=False,
            citation_url="https://www.fda.gov/example",
            citation_text="Safety Communication",
            date_added="2023/04",
        )
    )
    session.commit()


def test_health_check():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_check_returns_matched_and_unmatched_ingredients(db_session):
    _seed(db_session, "DMAA", "not_a_dietary_ingredient")

    with patch.object(match, "_llm_match", return_value=None):
        response = client.post("/api/check", json={"ingredients_text": "DMAA\nVitamin C"})

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == "1 flagged, 0 clear, 1 not FDA-flagged"

    by_name = {r["submitted_name"]: r for r in body["results"]}
    assert by_name["DMAA"]["status"] == "not_a_dietary_ingredient"
    assert by_name["DMAA"]["citation"] == "https://www.fda.gov/example"
    assert by_name["Vitamin C"]["status"] == "not_in_database"
    assert by_name["Vitamin C"]["matched_ingredient"] is None


def test_check_rejects_oversized_payload():
    response = client.post("/api/check", json={"ingredients_text": "x" * 6000})
    assert response.status_code == 422
