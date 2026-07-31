from ai.answer import EvidenceRegistry
from ai.retrieval import Evidence
from database.access.search import Provenance

_SOURCE = Provenance(source_system="test", endpoint_or_document_type="fixture", ingested_at="now")


def _evidence(entity_type: str, entity_id: str, *, number: int = 0) -> Evidence:
    return Evidence(
        number=number,
        entity_type=entity_type,
        entity_id=entity_id,
        content=f"{entity_type} {entity_id}",
        retrieval_confidence=0.5,
        entity_resolution_confidence=None,
        source=_SOURCE,
        external_url=None,
    )


def test_first_add_numbers_sequentially_from_one() -> None:
    registry = EvidenceRegistry()

    numbered = registry.add([_evidence("product", "A"), _evidence("warning", "B")])

    assert [item.number for item in numbered] == [1, 2]


def test_same_entity_reseen_in_a_later_call_keeps_its_original_number() -> None:
    registry = EvidenceRegistry()
    registry.add([_evidence("product", "A"), _evidence("warning", "B")])

    second_call = registry.add([_evidence("product", "A"), _evidence("recall", "C")])

    assert second_call[0].number == 1  # product A: same number as before
    assert second_call[1].number == 3  # recall C: newly seen, next number


def test_all_returns_every_distinct_item_in_first_seen_order() -> None:
    registry = EvidenceRegistry()
    registry.add([_evidence("product", "A")])
    registry.add([_evidence("product", "A"), _evidence("warning", "B")])

    all_items = registry.all()

    assert [(item.entity_type, item.entity_id) for item in all_items] == [
        ("product", "A"),
        ("warning", "B"),
    ]


def test_same_entity_id_different_entity_type_is_a_distinct_citation() -> None:
    """entity_id alone isn't a stable key -- an ingredient and a warning
    could theoretically share an id string from different ID sequences."""
    registry = EvidenceRegistry()

    numbered = registry.add([_evidence("ingredient", "1"), _evidence("warning", "1")])

    assert numbered[0].number != numbered[1].number


def test_empty_add_returns_empty_list() -> None:
    registry = EvidenceRegistry()

    assert registry.add([]) == []
    assert registry.all() == []
