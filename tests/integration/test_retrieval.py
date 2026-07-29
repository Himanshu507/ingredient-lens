from datetime import UTC, datetime

from sqlalchemy.orm import Session

from ai.retrieval import retrieve
from database.access.ingredients import ingredient_repository
from database.access.manufacturers import manufacturer_repository
from database.access.products import product_repository
from database.models.alias import Alias
from database.models.enums import (
    EntityType,
    ProductIngredientRole,
    RecallClassification,
    RecallStatus,
    RecordStatus,
    WarningCategory,
)
from database.models.product import ProductIngredient
from database.models.recall import Recall
from database.models.source import Source
from database.models.warning import Warning


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


def test_retrieve_finds_ingredient_via_alias_with_resolution_confidence(
    db_session: Session,
) -> None:
    """AI_PIPELINE.md Section 6: when a hit came through a fuzzy-matched alias,
    the alias's establishment confidence must be surfaced as
    entity_resolution_confidence, separate from retrieval_confidence."""
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
            confidence=0.93,
            source_id=source_id,
        )
    )
    db_session.flush()

    results = retrieve(db_session, "vitamin c")

    assert len(results) == 1
    hit = results[0]
    assert hit.number == 1
    assert hit.entity_type == "ingredient"
    assert hit.entity_id == ingredient.id
    assert hit.entity_resolution_confidence == 0.93
    assert hit.source.source_system == "test"


def test_retrieve_direct_name_match_has_no_resolution_confidence(db_session: Session) -> None:
    source_id = _make_source(db_session)
    ingredient_repository(db_session).create(
        name="Naproxen", normalized_name="naproxen", source_id=source_id
    )
    db_session.flush()

    results = retrieve(db_session, "naproxen")

    assert len(results) == 1
    assert results[0].entity_resolution_confidence is None


def test_retrieve_merges_and_ranks_across_entity_types(db_session: Session) -> None:
    source_id = _make_source(db_session)
    manufacturer = manufacturer_repository(db_session).create(
        name="Acme Pharma", normalized_name="acme pharma", source_id=source_id
    )
    ingredient = ingredient_repository(db_session).create(
        name="Ascorbic Acid", normalized_name="ascorbic acid", source_id=source_id
    )
    product = product_repository(db_session).create(
        name="Ascorbic Acid Tablets",
        product_type="dietary supplement",
        dosage_form="tablet",
        manufacturer_id=manufacturer.id,
        source_id=source_id,
    )
    assert product.current_version is not None
    db_session.add(
        ProductIngredient(
            product_version_id=product.current_version.id,
            ingredient_id=ingredient.id,
            role=ProductIngredientRole.ACTIVE,
        )
    )
    db_session.add(
        Warning(
            product_id=product.id,
            category=WarningCategory.PRECAUTION,
            text="Ascorbic acid may cause stomach upset in large doses",
            status=RecordStatus.ACTIVE,
            version_number=1,
            source_id=source_id,
        )
    )
    db_session.add(
        Recall(
            product_id=product.id,
            manufacturer_id=manufacturer.id,
            reason="Ascorbic acid tablets found under-strength",
            classification=RecallClassification.CLASS_III,
            status=RecallStatus.ONGOING,
            source_id=source_id,
        )
    )
    db_session.flush()

    results = retrieve(db_session, "ascorbic acid", limit=10)

    entity_types = {r.entity_type for r in results}
    assert entity_types == {"ingredient", "product", "warning", "recall"}
    # numbered 1..N, ordered by descending retrieval confidence
    assert [r.number for r in results] == list(range(1, len(results) + 1))
    ranks = [r.retrieval_confidence for r in results]
    assert ranks == sorted(ranks, reverse=True)

    product_evidence = next(r for r in results if r.entity_type == "product")
    assert "Acme Pharma" in product_evidence.content
    assert "precaution" in product_evidence.content.lower()


def test_retrieve_respects_limit_across_merged_results(db_session: Session) -> None:
    source_id = _make_source(db_session)
    for i in range(5):
        ingredient_repository(db_session).create(
            name=f"Test Ingredient {i}", normalized_name=f"test ingredient {i}", source_id=source_id
        )
    db_session.flush()

    results = retrieve(db_session, "test ingredient", limit=3)

    assert len(results) == 3
    assert [r.number for r in results] == [1, 2, 3]


def test_retrieve_no_match_returns_empty(db_session: Session) -> None:
    source_id = _make_source(db_session)
    ingredient_repository(db_session).create(
        name="Naproxen", normalized_name="naproxen", source_id=source_id
    )
    db_session.flush()

    assert retrieve(db_session, "acetaminophen") == []
