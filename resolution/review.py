"""Manual review queue decisions (ENTITY_RESOLUTION.md Section 7).

`candidate_a_id` is always the pre-existing entity the fuzzy match was
scored against; `candidate_b_id` is the entity provisionally created for the
incoming record while the review was pending (resolver.py never leaves an
incoming record unpersisted). Approval merges `candidate_b_id` into
`candidate_a_id` — the pre-existing entity's ID always survives (Section 9
point 1: "incoming data never displaces an established canonical ID").
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from database.access.ingredients import ingredient_repository
from database.access.manufacturers import manufacturer_repository
from database.models.alias import Alias
from database.models.entity_resolution_review import EntityResolutionReview
from database.models.enums import EntityType, RecordStatus, ReviewStatus
from database.models.product import ProductIngredient, ProductVersion
from database.models.reference import Reference
from database.models.source import Source
from normalization.text import normalize_name

_REVIEW_SOURCE_SYSTEM = "entity_resolution"
_REVIEW_SOURCE_ENDPOINT = "manual_review"


class ReviewNotPendingError(Exception):
    """A review was already decided — approve/reject only apply once."""


def _repository_for(entity_type: EntityType):  # type: ignore[no-untyped-def]
    if entity_type == EntityType.INGREDIENT:
        return ingredient_repository
    if entity_type == EntityType.MANUFACTURER:
        return manufacturer_repository
    raise ValueError(f"entity resolution does not apply to {entity_type}")


def _review_source_id(session: Session) -> int:
    """A dedicated `Source` for versions created by the review process itself
    (e.g. superseding a merged-away entity) — every row is attributable
    (DATABASE_DESIGN.md Section 1), even ones a human decision produced
    rather than an ingestion run. Reused across approvals, not one per call.
    """
    existing_id: int | None = session.execute(
        sa.select(Source.id).where(
            Source.source_system == _REVIEW_SOURCE_SYSTEM,
            Source.endpoint_or_document_type == _REVIEW_SOURCE_ENDPOINT,
        )
    ).scalar_one_or_none()
    if existing_id is not None:
        return existing_id

    source = Source(
        source_system=_REVIEW_SOURCE_SYSTEM,
        endpoint_or_document_type=_REVIEW_SOURCE_ENDPOINT,
        ingestion_run_id="manual",
        ingested_at=datetime.now(UTC),
    )
    session.add(source)
    session.flush()
    return source.id


def approve_review(session: Session, review: EntityResolutionReview, *, reviewed_by: str) -> str:
    """Merge `candidate_b_id` into `candidate_a_id` and record the decision.

    Per Section 9's merge semantics:
    - The surviving ID is always `candidate_a_id` — never the freshly
      created `candidate_b_id`.
    - `candidate_b_id`'s References and Aliases are re-pointed to the
      survivor, not discarded (accumulate, never overwritten).
    - `candidate_b_id`'s own name becomes a new Alias of the survivor, so
      the same pair is never re-queued (Section 7).
    - `candidate_b_id`'s identity/version rows are left in place — never
      deleted, preserving its provenance — but a new version marks it
      `superseded` (DATABASE_DESIGN.md Section 3's soft-delete status), so
      it stops being directly matchable by name (Strategies 2–3 only
      consider `active` entities) — otherwise the *next* lookup for that
      same name would find the superseded entity itself before ever
      reaching the alias that's supposed to redirect it to the survivor.
    """
    if review.status != ReviewStatus.PENDING:
        raise ReviewNotPendingError(f"review {review.id} is already {review.status.value}")

    winner_id = review.candidate_a_id
    loser_id = review.candidate_b_id
    entity_type = review.entity_type

    repository = _repository_for(entity_type)(session)
    loser = repository.get_current(loser_id)
    if loser is not None and loser.current_version is not None:
        loser_name = loser.current_version.name
        session.add(
            Alias(
                entity_type=entity_type,
                entity_id=winner_id,
                alias_text=loser_name,
                normalized_alias_text=normalize_name(loser_name),
                confidence=review.confidence_score,
                source_id=None,  # a manual decision, not tied to one ingestion source
            )
        )
        repository.add_version(
            loser_id,
            name=loser_name,
            normalized_name=normalize_name(loser_name),
            status=RecordStatus.SUPERSEDED,
            source_id=_review_source_id(session),
        )

    session.execute(
        sa.update(Reference).where(Reference.entity_id == loser_id).values(entity_id=winner_id)
    )
    session.execute(
        sa.update(Alias)
        .where(Alias.entity_type == entity_type, Alias.entity_id == loser_id)
        .values(entity_id=winner_id)
    )

    if entity_type == EntityType.INGREDIENT:
        _repoint_product_ingredients(session, loser_id=loser_id, winner_id=winner_id)
    elif entity_type == EntityType.MANUFACTURER:
        session.execute(
            sa.update(ProductVersion)
            .where(ProductVersion.manufacturer_id == loser_id)
            .values(manufacturer_id=winner_id)
        )

    review.status = ReviewStatus.APPROVED
    review.reviewed_by = reviewed_by
    review.reviewed_at = datetime.now(UTC)
    session.flush()
    return winner_id


def _repoint_product_ingredients(session: Session, *, loser_id: str, winner_id: str) -> None:
    """Re-point `product_ingredients` rows from loser to winner.

    A product might already link to the winner directly (e.g. mentioned
    under both names in one document) — in that case the loser's row is
    redundant and is dropped, not updated, to avoid violating the
    `(product_version_id, ingredient_id)` primary key.
    """
    loser_links = session.execute(
        sa.select(ProductIngredient).where(ProductIngredient.ingredient_id == loser_id)
    ).scalars()

    for link in loser_links:
        already_linked_to_winner = session.get(
            ProductIngredient, (link.product_version_id, winner_id)
        )
        if already_linked_to_winner is not None:
            session.delete(link)
        else:
            link.ingredient_id = winner_id
    session.flush()


def reject_review(session: Session, review: EntityResolutionReview, *, reviewed_by: str) -> None:
    """Record the two candidates as genuinely distinct entities.

    Both entities remain exactly as they are — no alias, no re-pointing.
    ENTITY_RESOLUTION.md specifies no mechanism to suppress a future,
    independently-generated match on this same pair (unlike approval's
    alias write-back); a rejection is a decision about these two specific
    records, not a standing rule.
    """
    if review.status != ReviewStatus.PENDING:
        raise ReviewNotPendingError(f"review {review.id} is already {review.status.value}")

    review.status = ReviewStatus.REJECTED
    review.reviewed_by = reviewed_by
    review.reviewed_at = datetime.now(UTC)
    session.flush()
