from ai.prompting import INSUFFICIENT_EVIDENCE_TEXT, SYSTEM_PROMPT, build_user_prompt
from ai.retrieval import Evidence
from database.access.search import Provenance


def _evidence(**overrides: object) -> Evidence:
    defaults: dict[str, object] = {
        "number": 1,
        "entity_type": "ingredient",
        "entity_id": "ING-1",
        "content": "Ingredient: Ascorbic Acid",
        "retrieval_confidence": 0.5,
        "entity_resolution_confidence": None,
        "source": Provenance(
            source_system="dailymed",
            endpoint_or_document_type="spl",
            ingested_at="2026-01-01T00:00:00+00:00",
        ),
    }
    defaults.update(overrides)
    return Evidence(**defaults)  # type: ignore[arg-type]


def test_system_prompt_states_insufficient_evidence_sentinel_exactly() -> None:
    assert INSUFFICIENT_EVIDENCE_TEXT in SYSTEM_PROMPT


def test_system_prompt_forbids_compliance_judgments() -> None:
    assert "compliance" in SYSTEM_PROMPT.lower()


def test_user_prompt_includes_question_and_evidence_number() -> None:
    prompt = build_user_prompt("does this contain vitamin C?", [_evidence()])
    assert "does this contain vitamin C?" in prompt
    assert "[1]" in prompt
    assert "Ascorbic Acid" in prompt
    assert "dailymed" in prompt


def test_user_prompt_surfaces_entity_resolution_confidence_when_present() -> None:
    prompt = build_user_prompt("q", [_evidence(entity_resolution_confidence=0.93)])
    assert "0.93" in prompt


def test_user_prompt_omits_resolution_confidence_note_when_absent() -> None:
    prompt = build_user_prompt("q", [_evidence(entity_resolution_confidence=None)])
    assert "entity resolution confidence" not in prompt


def test_user_prompt_renders_multiple_evidence_items_numbered() -> None:
    prompt = build_user_prompt(
        "q",
        [
            _evidence(number=1, content="first"),
            _evidence(number=2, content="second"),
        ],
    )
    assert "[1]" in prompt
    assert "[2]" in prompt
    assert "first" in prompt
    assert "second" in prompt
