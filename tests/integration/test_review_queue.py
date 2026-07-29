from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from database.access.ingredients import ingredient_repository
from database.access.products import product_repository
from database.models.alias import Alias
from database.models.entity_resolution_review import EntityResolutionReview
from database.models.enums import EntityType, ProductIngredientRole, ReferenceType, ReviewStatus
from database.models.product import ProductIngredient
from database.models.reference import Reference
from database.models.source import Source
from resolution.resolver import ResolutionCandidate, resolve_entity
from resolution.review import ReviewNotPendingError, approve_review, reject_review


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


def _queue_a_review(session: Session, source_id: int) -> EntityResolutionReview:
    repo = ingredient_repository(session)
    resolve_entity(
        session,
        entity_type=EntityType.INGREDIENT,
        candidate=ResolutionCandidate(name="Ascorbic Acid"),
        repository=repo,
        source_id=source_id,
    )
    resolve_entity(
        session,
        entity_type=EntityType.INGREDIENT,
        candidate=ResolutionCandidate(name="Ascorbic Acid, USP"),
        repository=repo,
        source_id=source_id,
    )
    return session.execute(sa.select(EntityResolutionReview)).scalar_one()


def test_approve_merges_loser_into_winner_and_writes_alias(db_session: Session) -> None:
    source_id = _make_source(db_session)
    review = _queue_a_review(db_session, source_id)
    winner_id = review.candidate_a_id

    result = approve_review(db_session, review, reviewed_by="qa-reviewer")

    assert result == winner_id
    assert review.status == ReviewStatus.APPROVED
    assert review.reviewed_by == "qa-reviewer"
    assert review.reviewed_at is not None

    alias = db_session.execute(sa.select(Alias).where(Alias.entity_id == winner_id)).scalar_one()
    assert alias.alias_text == "Ascorbic Acid, USP"
    assert alias.normalized_alias_text == "ascorbic acid, usp"


def test_approved_pair_never_re_queues(db_session: Session) -> None:
    """Section 7: on approval, the same pair is never re-queued again --
    resolving the loser's exact name a second time now hits the alias
    (Strategy 2) directly."""
    source_id = _make_source(db_session)
    review = _queue_a_review(db_session, source_id)
    winner_id = review.candidate_a_id
    approve_review(db_session, review, reviewed_by="qa-reviewer")

    repo = ingredient_repository(db_session)
    again_id = resolve_entity(
        db_session,
        entity_type=EntityType.INGREDIENT,
        candidate=ResolutionCandidate(name="Ascorbic Acid, USP"),
        repository=repo,
        source_id=source_id,
    )

    assert again_id == winner_id
    reviews = db_session.execute(sa.select(sa.func.count()).select_from(EntityResolutionReview))
    assert reviews.scalar_one() == 1  # no second review created


def test_approve_repoints_existing_references_from_loser_to_winner(db_session: Session) -> None:
    source_id = _make_source(db_session)
    review = _queue_a_review(db_session, source_id)
    winner_id, loser_id = review.candidate_a_id, review.candidate_b_id

    # Give the loser a Reference before it gets merged away.
    db_session.add(
        Reference(
            entity_type=EntityType.INGREDIENT,
            entity_id=loser_id,
            reference_type=ReferenceType.CAS,
            reference_value="50-81-7",
            source_id=source_id,
        )
    )
    db_session.flush()

    approve_review(db_session, review, reviewed_by="qa-reviewer")

    reference = db_session.execute(
        sa.select(Reference).where(Reference.reference_value == "50-81-7")
    ).scalar_one()
    assert reference.entity_id == winner_id


def test_approve_repoints_product_ingredients_avoiding_pk_collision(db_session: Session) -> None:
    """A product that already links to the winner directly must not end up
    with a duplicate (product_version_id, ingredient_id) row after the
    loser's link is re-pointed -- the loser's redundant row is dropped."""
    source_id = _make_source(db_session)
    review = _queue_a_review(db_session, source_id)
    winner_id, loser_id = review.candidate_a_id, review.candidate_b_id

    product = product_repository(db_session).create(
        name="Test Product",
        product_type=None,
        dosage_form=None,
        manufacturer_id=None,
        source_id=source_id,
    )
    assert product.current_version is not None
    # This product links to BOTH the winner and the loser already.
    db_session.add(
        ProductIngredient(
            product_version_id=product.current_version.id,
            ingredient_id=winner_id,
            role=ProductIngredientRole.ACTIVE,
        )
    )
    db_session.add(
        ProductIngredient(
            product_version_id=product.current_version.id,
            ingredient_id=loser_id,
            role=ProductIngredientRole.INACTIVE,
        )
    )
    db_session.flush()

    approve_review(db_session, review, reviewed_by="qa-reviewer")

    links = (
        db_session.execute(
            sa.select(ProductIngredient).where(
                ProductIngredient.product_version_id == product.current_version.id
            )
        )
        .scalars()
        .all()
    )
    assert len(links) == 1
    assert links[0].ingredient_id == winner_id


def test_approve_twice_raises(db_session: Session) -> None:
    source_id = _make_source(db_session)
    review = _queue_a_review(db_session, source_id)
    approve_review(db_session, review, reviewed_by="qa-reviewer")

    with pytest.raises(ReviewNotPendingError):
        approve_review(db_session, review, reviewed_by="someone-else")


def test_reject_leaves_both_entities_independent(db_session: Session) -> None:
    source_id = _make_source(db_session)
    review = _queue_a_review(db_session, source_id)
    winner_id, loser_id = review.candidate_a_id, review.candidate_b_id

    reject_review(db_session, review, reviewed_by="qa-reviewer")

    assert review.status == ReviewStatus.REJECTED
    assert review.reviewed_by == "qa-reviewer"

    # No alias written, both entities remain distinct and untouched.
    assert db_session.execute(sa.select(sa.func.count()).select_from(Alias)).scalar_one() == 0
    repo = ingredient_repository(db_session)
    assert repo.get_current(winner_id) is not None
    assert repo.get_current(loser_id) is not None
