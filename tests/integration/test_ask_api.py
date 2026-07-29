from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import ai.answer as answer_module
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


def test_ask_endpoint_returns_cited_answer(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
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

    monkeypatch.setattr(
        answer_module,
        "generate",
        lambda system_prompt, user_prompt: "This product contains Vitamin C. [1]",
    )

    app.dependency_overrides[get_session] = lambda: db_session
    try:
        client = TestClient(app)
        response = client.post("/ask", json={"question": "vitamin c"})
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 200
    body = response.json()
    assert body["insufficient_evidence"] is False
    assert body["text"] == "This product contains Vitamin C. [1]"
    assert len(body["references"]) == 1
    assert body["references"][0]["entity_id"] == ingredient.id


def test_ask_endpoint_returns_insufficient_evidence_for_empty_retrieval(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail_if_called(*args: object, **kwargs: object) -> str:
        raise AssertionError("LLM must not be called when retrieval returns nothing")

    monkeypatch.setattr(answer_module, "generate", _fail_if_called)

    app.dependency_overrides[get_session] = lambda: db_session
    try:
        client = TestClient(app)
        response = client.post("/ask", json={"question": "unobtainium"})
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 200
    body = response.json()
    assert body["insufficient_evidence"] is True
    assert body["references"] == []


def test_ask_endpoint_requires_question_field() -> None:
    client = TestClient(app)
    response = client.post("/ask", json={})
    assert response.status_code == 422


def test_ui_is_served_as_a_static_page() -> None:
    client = TestClient(app)
    response = client.get("/ui/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Search" in response.text
    assert "Ask a question" in response.text


def test_openapi_schema_documents_ask_endpoint() -> None:
    client = TestClient(app)
    schema = client.get("/openapi.json").json()
    assert "/ask" in schema["paths"]
