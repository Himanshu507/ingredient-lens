from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from database.access.ingredients import ingredient_repository
from database.models.alias import Alias
from database.models.entity_resolution_review import EntityResolutionReview
from database.models.enums import EntityType, ReviewStatus
from database.models.ingredient import Ingredient
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


def test_high_confidence_variant_auto_merges_and_records_alias(db_session: Session) -> None:
    """Real trigram score: similarity('beta carotene', 'beta-carotene') = 1.0
    (verified against Postgres) — a punctuation variant normalization alone
    doesn't collapse (space vs hyphen are different normalized strings)."""
    source_id = _make_source(db_session)
    repo = ingredient_repository(db_session)

    original_id = resolve_entity(
        db_session,
        entity_type=EntityType.INGREDIENT,
        candidate=ResolutionCandidate(name="Beta Carotene"),
        repository=repo,
        source_id=source_id,
    )
    variant_id = resolve_entity(
        db_session,
        entity_type=EntityType.INGREDIENT,
        candidate=ResolutionCandidate(name="Beta-Carotene"),
        repository=repo,
        source_id=source_id,
    )

    assert original_id == variant_id
    assert _count(db_session, Ingredient) == 1
    assert _count(db_session, EntityResolutionReview) == 0

    alias = db_session.execute(
        sa.select(Alias).where(Alias.entity_type == EntityType.INGREDIENT)
    ).scalar_one()
    assert alias.entity_id == original_id
    assert alias.alias_text == "Beta-Carotene"
    assert alias.confidence == 1.0

    # And now the exact-alias lookup (Strategy 2) catches it directly --
    # no need to repeat fuzzy matching for the same string again.
    again_id = resolve_entity(
        db_session,
        entity_type=EntityType.INGREDIENT,
        candidate=ResolutionCandidate(name="Beta-Carotene"),
        repository=repo,
        source_id=source_id,
    )
    assert again_id == original_id
    assert _count(db_session, Alias) == 1  # not written a second time


def test_medium_confidence_variant_queues_for_review_not_auto_merge(db_session: Session) -> None:
    """Real trigram score: similarity('ascorbic acid', 'ascorbic acid, usp')
    ~= 0.76 -- between thresholds, plausible but not certain."""
    source_id = _make_source(db_session)
    repo = ingredient_repository(db_session)

    original_id = resolve_entity(
        db_session,
        entity_type=EntityType.INGREDIENT,
        candidate=ResolutionCandidate(name="Ascorbic Acid"),
        repository=repo,
        source_id=source_id,
    )
    incoming_id = resolve_entity(
        db_session,
        entity_type=EntityType.INGREDIENT,
        candidate=ResolutionCandidate(name="Ascorbic Acid, USP"),
        repository=repo,
        source_id=source_id,
    )

    # Not merged -- the incoming record is its own entity, provisionally,
    # while the match awaits review (Section 7).
    assert original_id != incoming_id
    assert _count(db_session, Ingredient) == 2

    review = db_session.execute(sa.select(EntityResolutionReview)).scalar_one()
    assert review.status == ReviewStatus.PENDING
    assert review.entity_type == EntityType.INGREDIENT
    assert review.candidate_a_id == original_id
    assert review.candidate_b_id == incoming_id
    assert 0.75 <= review.confidence_score < 0.92


def test_low_confidence_pair_never_merges_and_never_queues(db_session: Session) -> None:
    """The system is biased toward under-merging (Section 1) -- 'Vitamin B12'
    and 'Vitamin B6' (real score ~0.64) must land as two fully independent
    entities, no review either (below even the medium threshold)."""
    source_id = _make_source(db_session)
    repo = ingredient_repository(db_session)

    b12_id = resolve_entity(
        db_session,
        entity_type=EntityType.INGREDIENT,
        candidate=ResolutionCandidate(name="Vitamin B12"),
        repository=repo,
        source_id=source_id,
    )
    b6_id = resolve_entity(
        db_session,
        entity_type=EntityType.INGREDIENT,
        candidate=ResolutionCandidate(name="Vitamin B6"),
        repository=repo,
        source_id=source_id,
    )

    assert b12_id != b6_id
    assert _count(db_session, Ingredient) == 2
    assert _count(db_session, EntityResolutionReview) == 0


def test_vitamin_c_ascorbic_acid_do_not_fuzzy_match(db_session: Session) -> None:
    """The founding-vision example (ENTITY_RESOLUTION.md Section 1) -- and it
    is *not* solvable by fuzzy string matching: similarity('vitamin c',
    'ascorbic acid') = 0.0 exactly (verified against Postgres), since the
    strings share no substring at all. "There is no typo to fix; there is a
    synonym relationship to know" is the doc's own framing for exactly this
    case. This pair only merges via an authoritative identifier shared by
    both sources (Brick 10's Strategy 1 -- see
    test_entity_resolution.py::test_unii_match_merges_even_with_completely_different_names)
    or a future curated synonym dictionary (Section 5) -- not this strategy.
    """
    source_id = _make_source(db_session)
    repo = ingredient_repository(db_session)

    vitamin_c_id = resolve_entity(
        db_session,
        entity_type=EntityType.INGREDIENT,
        candidate=ResolutionCandidate(name="Vitamin C"),
        repository=repo,
        source_id=source_id,
    )
    ascorbic_acid_id = resolve_entity(
        db_session,
        entity_type=EntityType.INGREDIENT,
        candidate=ResolutionCandidate(name="Ascorbic Acid"),
        repository=repo,
        source_id=source_id,
    )

    assert vitamin_c_id != ascorbic_acid_id
    assert _count(db_session, Ingredient) == 2
    assert _count(db_session, EntityResolutionReview) == 0
