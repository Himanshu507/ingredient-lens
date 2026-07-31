from ai.prompting import INSUFFICIENT_EVIDENCE_TEXT, TOOL_SYSTEM_PROMPT, build_evidence_block
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
        "external_url": None,
    }
    defaults.update(overrides)
    return Evidence(**defaults)  # type: ignore[arg-type]


def test_system_prompt_states_insufficient_evidence_sentinel_exactly() -> None:
    assert INSUFFICIENT_EVIDENCE_TEXT in TOOL_SYSTEM_PROMPT


def test_system_prompt_forbids_compliance_judgments() -> None:
    assert "compliance" in TOOL_SYSTEM_PROMPT.lower()


def test_system_prompt_describes_the_search_tool() -> None:
    assert "search_evidence" in TOOL_SYSTEM_PROMPT


def test_system_prompt_tells_model_to_reformulate_not_ask_user() -> None:
    assert "rephrase" in TOOL_SYSTEM_PROMPT.lower()


def test_evidence_block_includes_number_and_content() -> None:
    block = build_evidence_block([_evidence()])
    assert "[1]" in block
    assert "Ascorbic Acid" in block
    assert "dailymed" in block


def test_evidence_block_surfaces_entity_resolution_confidence_when_present() -> None:
    block = build_evidence_block([_evidence(entity_resolution_confidence=0.93)])
    assert "0.93" in block


def test_evidence_block_omits_resolution_confidence_note_when_absent() -> None:
    block = build_evidence_block([_evidence(entity_resolution_confidence=None)])
    assert "entity resolution confidence" not in block


def test_evidence_block_renders_multiple_items_numbered() -> None:
    block = build_evidence_block(
        [
            _evidence(number=1, content="first"),
            _evidence(number=2, content="second"),
        ]
    )
    assert "[1]" in block
    assert "[2]" in block
    assert "first" in block
    assert "second" in block


def test_evidence_block_reports_no_results_for_empty_list() -> None:
    block = build_evidence_block([])
    assert "no matching records" in block.lower()
