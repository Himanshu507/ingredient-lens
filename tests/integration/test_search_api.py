from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.deps import get_session
from api.main import app
from database.access.ingredients import ingredient_repository
from database.models.alias import Alias
from database.models.enums import EntityType
from database.models.source import Source


def _make_source(session: Session) -> int:
    source = Source(
        source_system="test",
        endpoint_or_document_type="unit-test-fixture",
        ingestion_run_id="run-1",
        ingested_at=datetime.now(UTC),
    )
    session.add(source)
    session.flush()
    return source.id


def test_get_ingredients_endpoint_finds_entity_via_alias(db_session: Session) -> None:
    source_id = _make_source(db_session)
    ingredient = ingredient_repository(db_session).create(
        name="Ascorbic Acid", normalized_name="ascorbic acid", source_id=source_id
    )
    db_session.add(
        Alias(
            entity_type=EntityType.INGREDIENT,
            entity_id=ingredient.id,
            alias_text="Vitamin C",
            normalized_alias_text="vitamin c",
            confidence=1.0,
            source_id=source_id,
        )
    )
    db_session.flush()

    app.dependency_overrides[get_session] = lambda: db_session
    try:
        client = TestClient(app)
        response = client.get("/ingredients", params={"q": "vitamin c"})
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == ingredient.id
    assert body[0]["name"] == "Ascorbic Acid"
    assert body[0]["source"]["source_system"] == "test"


def test_get_ingredients_requires_query_param() -> None:
    client = TestClient(app)
    response = client.get("/ingredients")
    assert response.status_code == 422  # missing required `q`


def test_search_endpoints_documented_in_openapi_schema() -> None:
    client = TestClient(app)
    schema = client.get("/openapi.json").json()
    assert set(schema["paths"].keys()) >= {
        "/",
        "/health",
        "/ingredients",
        "/products",
        "/warnings",
        "/recalls",
    }
