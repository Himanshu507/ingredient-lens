from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

import ai.answer as answer_module
from ai.answer import MAX_TOOL_ITERATIONS, ask
from ai.llm import CompletionResult, ToolCall
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


def _seed_test_compound(session: Session) -> str:
    source_id = _make_source(session)
    ingredient = ingredient_repository(session).create(
        name="Zyxwvutest Compound", normalized_name="zyxwvutest compound", source_id=source_id
    )
    session.add(
        Alias(
            entity_type=EntityType.INGREDIENT,
            entity_id=ingredient.id,
            alias_text="Zyxwvutest C",
            normalized_alias_text="zyxwvutest c",
            confidence=1.0,
            source_id=source_id,
        )
    )
    session.flush()
    return ingredient.id


def _tool_call(query: str, *, call_id: str = "call-1") -> CompletionResult:
    return CompletionResult(
        content=None,
        tool_calls=[ToolCall(id=call_id, name="search_evidence", arguments={"query": query})],
    )


def _final(text: str) -> CompletionResult:
    return CompletionResult(content=text, tool_calls=[])


def _mock_turns(monkeypatch: pytest.MonkeyPatch, turns: list[CompletionResult]) -> None:
    """Feeds `turns` to `generate_with_tools` in order, one per call --
    real `ask()` code drives the loop; this just scripts what the model
    "says" at each turn without a real network call."""
    iterator: Iterator[CompletionResult] = iter(turns)

    def _fake(messages: list[object], *, tools: list[object]) -> CompletionResult:
        try:
            return next(iterator)
        except StopIteration:
            raise AssertionError("generate_with_tools called more times than scripted") from None

    monkeypatch.setattr(answer_module, "generate_with_tools", _fake)


def test_ask_with_strong_evidence_and_correctly_cited_answer_succeeds(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    ingredient_id = _seed_test_compound(db_session)
    _mock_turns(
        monkeypatch,
        [_tool_call("zyxwvutest c"), _final("This product contains Zyxwvutest C. [1]")],
    )

    result = ask(db_session, "zyxwvutest c")

    assert not result.insufficient_evidence
    assert result.text == "This product contains Zyxwvutest C. [1]"
    assert len(result.references) == 1
    assert result.references[0].entity_id == ingredient_id
    assert result.references[0].entity_type == "ingredient"
    assert result.references[0].source.source_system == "test"


def test_ask_with_no_matching_evidence_falls_back(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The model still gets called first (it decides whether/what to
    search) -- an empty tool result is expected to lead the model to the
    insufficient-evidence sentinel, not skip the LLM call entirely."""
    _mock_turns(
        monkeypatch,
        [_tool_call("unobtainium"), _final(INSUFFICIENT_EVIDENCE_TEXT)],
    )

    result = ask(db_session, "unobtainium")

    assert result.insufficient_evidence
    assert result.text == INSUFFICIENT_EVIDENCE_TEXT
    assert result.references == []


def test_ask_falls_back_when_model_declares_no_evidence(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_test_compound(db_session)
    _mock_turns(
        monkeypatch,
        [_tool_call("zyxwvutest c"), _final(INSUFFICIENT_EVIDENCE_TEXT)],
    )

    result = ask(db_session, "zyxwvutest c")

    assert result.insufficient_evidence
    assert result.references == []


def test_ask_rejects_uncited_answer_and_falls_back(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AI_PIPELINE.md Section 7 point 4: an answer failing citation
    verification is never shown to the user as-is."""
    _seed_test_compound(db_session)
    _mock_turns(
        monkeypatch,
        [_tool_call("zyxwvutest c"), _final("This product definitely contains Zyxwvutest C.")],
    )

    result = ask(db_session, "zyxwvutest c")

    assert result.insufficient_evidence
    assert result.text == INSUFFICIENT_EVIDENCE_TEXT
    assert result.references == []


def test_ask_rejects_out_of_range_citation_and_falls_back(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_test_compound(db_session)
    _mock_turns(
        monkeypatch,
        [_tool_call("zyxwvutest c"), _final("This product contains Zyxwvutest C. [99]")],
    )

    result = ask(db_session, "zyxwvutest c")

    assert result.insufficient_evidence


def test_ask_only_returns_references_for_cited_evidence_numbers(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_id = _make_source(db_session)
    ingredient_repository(db_session).create(
        name="Zyxwvutest Compound Variant A",
        normalized_name="zyxwvutest compound variant a",
        source_id=source_id,
    )
    ingredient_repository(db_session).create(
        name="Zyxwvutest Compound Variant B",
        normalized_name="zyxwvutest compound variant b",
        source_id=source_id,
    )
    db_session.flush()
    _mock_turns(
        monkeypatch,
        [
            _tool_call("zyxwvutest compound variant"),
            _final("Only variant A is mentioned here. [1]"),
        ],
    )

    result = ask(db_session, "zyxwvutest compound variant", retrieval_limit=10)

    assert not result.insufficient_evidence
    assert len(result.references) == 1
    assert result.references[0].number == 1


def test_ask_can_search_multiple_times_before_answering(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point of tool-calling: a first, unhelpful search doesn't
    end the conversation -- the model can try again with a different query
    and still produce a correctly cited answer from the second search."""
    ingredient_id = _seed_test_compound(db_session)
    _mock_turns(
        monkeypatch,
        [
            _tool_call("unobtainium", call_id="call-1"),
            _tool_call("zyxwvutest c", call_id="call-2"),
            _final("This product contains Zyxwvutest C. [1]"),
        ],
    )

    result = ask(db_session, "does this have zyxwvutest c in it")

    assert not result.insufficient_evidence
    assert len(result.references) == 1
    assert result.references[0].entity_id == ingredient_id


def test_ask_reuses_stable_citation_number_when_same_evidence_resurfaces(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Searching "zyxwvutest c" twice (e.g. the model refining its query)
    must not assign the same product a second citation number -- the
    second search's results should reuse number [1], not become [2]."""
    ingredient_id = _seed_test_compound(db_session)
    _mock_turns(
        monkeypatch,
        [
            _tool_call("zyxwvutest c", call_id="call-1"),
            _tool_call("zyxwvutest c", call_id="call-2"),
            _final("This product contains Zyxwvutest C. [1]"),
        ],
    )

    result = ask(db_session, "zyxwvutest c")

    assert not result.insufficient_evidence
    assert len(result.references) == 1
    assert result.references[0].number == 1
    assert result.references[0].entity_id == ingredient_id


def test_ask_falls_back_when_tool_iterations_exhausted(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the model never stops calling the tool, the loop must still
    terminate (bounded by MAX_TOOL_ITERATIONS) rather than call the LLM
    forever."""
    _seed_test_compound(db_session)
    _mock_turns(
        monkeypatch,
        [_tool_call(f"zyxwvutest c {i}", call_id=f"call-{i}") for i in range(MAX_TOOL_ITERATIONS)],
    )

    result = ask(db_session, "zyxwvutest c")

    assert result.insufficient_evidence
    assert result.text == INSUFFICIENT_EVIDENCE_TEXT
