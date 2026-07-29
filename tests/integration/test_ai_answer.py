from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

import ai.answer as answer_module
from ai.answer import ask
from ai.prompting import INSUFFICIENT_EVIDENCE_TEXT
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


def _seed_ascorbic_acid(session: Session) -> str:
    source_id = _make_source(session)
    ingredient = ingredient_repository(session).create(
        name="Ascorbic Acid", normalized_name="ascorbic acid", source_id=source_id
    )
    session.add(
        Alias(
            entity_type=EntityType.INGREDIENT,
            entity_id=ingredient.id,
            alias_text="Vitamin C",
            normalized_alias_text="vitamin c",
            confidence=1.0,
            source_id=source_id,
        )
    )
    session.flush()
    return ingredient.id


def test_ask_with_no_retrieval_results_returns_insufficient_evidence_without_calling_llm(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail_if_called(*args: object, **kwargs: object) -> str:
        raise AssertionError("LLM must not be called when retrieval returns nothing")

    monkeypatch.setattr(answer_module, "generate", _fail_if_called)

    result = ask(db_session, "unobtainium")

    assert result.insufficient_evidence
    assert result.text == INSUFFICIENT_EVIDENCE_TEXT
    assert result.references == []


def test_ask_with_strong_evidence_and_correctly_cited_answer_succeeds(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    ingredient_id = _seed_ascorbic_acid(db_session)

    monkeypatch.setattr(
        answer_module,
        "generate",
        lambda system_prompt, user_prompt: "This product contains Vitamin C. [1]",
    )

    result = ask(db_session, "vitamin c")

    assert not result.insufficient_evidence
    assert result.text == "This product contains Vitamin C. [1]"
    assert len(result.references) == 1
    assert result.references[0].entity_id == ingredient_id
    assert result.references[0].entity_type == "ingredient"
    assert result.references[0].source.source_system == "test"


def test_ask_falls_back_when_model_declares_no_evidence(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_ascorbic_acid(db_session)
    monkeypatch.setattr(
        answer_module, "generate", lambda system_prompt, user_prompt: INSUFFICIENT_EVIDENCE_TEXT
    )

    result = ask(db_session, "vitamin c")

    assert result.insufficient_evidence
    assert result.references == []


def test_ask_rejects_uncited_answer_and_falls_back(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AI_PIPELINE.md Section 7 point 4: an answer failing citation
    verification is never shown to the user as-is."""
    _seed_ascorbic_acid(db_session)
    monkeypatch.setattr(
        answer_module,
        "generate",
        lambda system_prompt, user_prompt: "This product definitely contains Vitamin C.",
    )

    result = ask(db_session, "vitamin c")

    assert result.insufficient_evidence
    assert result.text == INSUFFICIENT_EVIDENCE_TEXT
    assert result.references == []


def test_ask_rejects_out_of_range_citation_and_falls_back(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_ascorbic_acid(db_session)
    monkeypatch.setattr(
        answer_module,
        "generate",
        lambda system_prompt, user_prompt: "This product contains Vitamin C. [99]",
    )

    result = ask(db_session, "vitamin c")

    assert result.insufficient_evidence


def test_ask_only_returns_references_for_cited_evidence_numbers(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_id = _make_source(db_session)
    ingredient_repository(db_session).create(
        name="Ascorbic Acid Variant A",
        normalized_name="ascorbic acid variant a",
        source_id=source_id,
    )
    ingredient_repository(db_session).create(
        name="Ascorbic Acid Variant B",
        normalized_name="ascorbic acid variant b",
        source_id=source_id,
    )
    db_session.flush()

    monkeypatch.setattr(
        answer_module,
        "generate",
        lambda system_prompt, user_prompt: "Only variant A is mentioned here. [1]",
    )

    result = ask(db_session, "ascorbic acid variant", retrieval_limit=10)

    assert not result.insufficient_evidence
    assert len(result.references) == 1
    assert result.references[0].number == 1
