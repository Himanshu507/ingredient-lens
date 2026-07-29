from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from database.access.ingredients import ingredient_repository
from database.access.manufacturers import manufacturer_repository
from database.models.enums import EntityType, ReferenceType
from database.models.ingredient import Ingredient
from database.models.manufacturer import Manufacturer
from database.models.reference import Reference
from database.models.source import Source
from resolution.resolver import ResolutionCandidate, resolve_entity


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


def _count(session: Session, model: type) -> int:
    return session.execute(sa.select(sa.func.count()).select_from(model)).scalar_one()


def test_exact_normalized_name_match_merges_across_case_and_whitespace(
    db_session: Session,
) -> None:
    """ENTITY_RESOLUTION.md Section 5: exact match on normalized name."""
    source_id = _make_source(db_session)
    repo = ingredient_repository(db_session)

    first_id = resolve_entity(
        db_session,
        entity_type=EntityType.INGREDIENT,
        candidate=ResolutionCandidate(name="Vitamin C"),
        repository=repo,
        source_id=source_id,
    )
    second_id = resolve_entity(
        db_session,
        entity_type=EntityType.INGREDIENT,
        candidate=ResolutionCandidate(name="  VITAMIN   C  "),
        repository=repo,
        source_id=source_id,
    )

    assert first_id == second_id
    assert _count(db_session, Ingredient) == 1


def test_unii_match_merges_even_with_completely_different_names(db_session: Session) -> None:
    """ENTITY_RESOLUTION.md Section 4: this is the founding-vision example —
    "Vitamin C" (openFDA-style) and "Ascorbic Acid" (DailyMed-style) share a
    UNII and must merge, even though the strings share no similarity at all."""
    source_id = _make_source(db_session)
    repo = ingredient_repository(db_session)
    shared_unii = "PQ6CK8PD0R"

    vitamin_c_id = resolve_entity(
        db_session,
        entity_type=EntityType.INGREDIENT,
        candidate=ResolutionCandidate(
            name="Vitamin C", identifier_type=ReferenceType.UNII, identifier_value=shared_unii
        ),
        repository=repo,
        source_id=source_id,
    )
    ascorbic_acid_id = resolve_entity(
        db_session,
        entity_type=EntityType.INGREDIENT,
        candidate=ResolutionCandidate(
            name="ASCORBIC ACID", identifier_type=ReferenceType.UNII, identifier_value=shared_unii
        ),
        repository=repo,
        source_id=source_id,
    )

    assert vitamin_c_id == ascorbic_acid_id
    assert _count(db_session, Ingredient) == 1

    # The surviving entity's Reference is the UNII from whichever record
    # created it first -- attached once, not duplicated on the second hit.
    refs = _count(db_session, Reference)
    assert refs == 1


def test_different_unii_and_different_name_never_merge(db_session: Session) -> None:
    """The system is biased toward under-merging (ENTITY_RESOLUTION.md Section 1)
    -- "Vitamin B12" and "Vitamin B6" must never collapse into one entity."""
    source_id = _make_source(db_session)
    repo = ingredient_repository(db_session)

    b12_id = resolve_entity(
        db_session,
        entity_type=EntityType.INGREDIENT,
        candidate=ResolutionCandidate(
            name="Vitamin B12", identifier_type=ReferenceType.UNII, identifier_value="P6YC3EG204"
        ),
        repository=repo,
        source_id=source_id,
    )
    b6_id = resolve_entity(
        db_session,
        entity_type=EntityType.INGREDIENT,
        candidate=ResolutionCandidate(
            name="Vitamin B6", identifier_type=ReferenceType.UNII, identifier_value="KZE8253M0O"
        ),
        repository=repo,
        source_id=source_id,
    )

    assert b12_id != b6_id
    assert _count(db_session, Ingredient) == 2


def test_unii_checked_before_name_when_both_present(db_session: Session) -> None:
    """Strategy 1 (identifier) wins over Strategy 2 (name) -- a record whose
    normalized name looks new but whose UNII matches an existing entity must
    still merge into that entity, not create a second one under the new name."""
    source_id = _make_source(db_session)
    repo = ingredient_repository(db_session)
    shared_unii = "PQ6CK8PD0R"

    original_id = resolve_entity(
        db_session,
        entity_type=EntityType.INGREDIENT,
        candidate=ResolutionCandidate(
            name="Ascorbic Acid", identifier_type=ReferenceType.UNII, identifier_value=shared_unii
        ),
        repository=repo,
        source_id=source_id,
    )
    relabeled_id = resolve_entity(
        db_session,
        entity_type=EntityType.INGREDIENT,
        candidate=ResolutionCandidate(
            name="Vitamin C (Ascorbic Acid, USP)",
            identifier_type=ReferenceType.UNII,
            identifier_value=shared_unii,
        ),
        repository=repo,
        source_id=source_id,
    )

    assert original_id == relabeled_id
    assert _count(db_session, Ingredient) == 1


def test_manufacturer_resolution_merges_via_duns(db_session: Session) -> None:
    """ENTITY_RESOLUTION.md Section 8: manufacturer resolution follows the
    identical pipeline, using an authoritative identifier (DUNS/FDA labeler
    code) in place of CAS/UNII."""
    source_id = _make_source(db_session)
    repo = manufacturer_repository(db_session)
    duns = "006959555"

    first_id = resolve_entity(
        db_session,
        entity_type=EntityType.MANUFACTURER,
        candidate=ResolutionCandidate(
            name="Meijer Distribution Inc",
            identifier_type=ReferenceType.DUNS,
            identifier_value=duns,
        ),
        repository=repo,
        source_id=source_id,
    )
    second_id = resolve_entity(
        db_session,
        entity_type=EntityType.MANUFACTURER,
        candidate=ResolutionCandidate(
            name="Meijer Distribution, Inc.",  # slightly different string
            identifier_type=ReferenceType.DUNS,
            identifier_value=duns,
        ),
        repository=repo,
        source_id=source_id,
    )

    assert first_id == second_id
    assert _count(db_session, Manufacturer) == 1
