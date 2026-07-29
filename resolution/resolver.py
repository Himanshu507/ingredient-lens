"""Entity resolution: the full three-strategy pipeline from ENTITY_RESOLUTION.md.

Every incoming Ingredient/Manufacturer candidate is matched against existing
canonical entities, highest-confidence strategy first, before ever creating a
new one:

1. Authoritative identifier exact match (CAS/UNII for ingredients, FDA labeler
   code/DUNS for manufacturers) — definitive, no confidence score needed
   (Section 4).
2. Exact match on normalized name or known alias (Section 5).
3. Fuzzy trigram matching (resolution/fuzzy.py) — auto-merge above the high
   threshold, manual review queue between thresholds, otherwise no match
   (Section 6).

A candidate that matches none of the three becomes a brand-new canonical
entity, never a silent guess.
"""

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.orm import Session

from database.access.versioned_repository import VersionedEntityRepository
from database.models.alias import Alias
from database.models.entity_resolution_review import EntityResolutionReview
from database.models.enums import EntityType, RecordStatus, ReferenceType, ReviewStatus
from database.models.reference import Reference
from normalization.text import normalize_name
from resolution.fuzzy import fuzzy_match


@dataclass(frozen=True)
class ResolutionCandidate:
    name: str
    identifier_type: ReferenceType | None = None
    identifier_value: str | None = None


def _find_by_reference(
    session: Session, entity_type: EntityType, reference_type: ReferenceType, value: str
) -> str | None:
    reference = session.execute(
        sa.select(Reference).where(
            Reference.entity_type == entity_type,
            Reference.reference_type == reference_type,
            Reference.reference_value == value,
        )
    ).scalar_one_or_none()
    return reference.entity_id if reference is not None else None


def _find_by_normalized_name_or_alias(
    session: Session,
    entity_type: EntityType,
    repository: VersionedEntityRepository,  # type: ignore[type-arg]
    normalized_name: str,
) -> str | None:
    identity_model = repository.identity_model
    version_model = repository.version_model

    current_version_match: str | None = session.execute(
        sa.select(identity_model.id)
        .join(version_model, version_model.id == identity_model.current_version_id)
        .where(
            version_model.normalized_name == normalized_name,
            version_model.status == RecordStatus.ACTIVE,
        )
        .limit(1)
    ).scalar_one_or_none()
    if current_version_match is not None:
        return current_version_match

    alias_match: str | None = session.execute(
        sa.select(Alias.entity_id)
        .where(
            Alias.entity_type == entity_type,
            Alias.normalized_alias_text == normalized_name,
        )
        .limit(1)
    ).scalar_one_or_none()
    return alias_match


def _attach_reference_if_present(
    session: Session,
    entity_type: EntityType,
    entity_id: str,
    candidate: ResolutionCandidate,
    source_id: int,
) -> None:
    if candidate.identifier_type is not None and candidate.identifier_value:
        session.add(
            Reference(
                entity_type=entity_type,
                entity_id=entity_id,
                reference_type=candidate.identifier_type,
                reference_value=candidate.identifier_value,
                source_id=source_id,
            )
        )


def resolve_entity(
    session: Session,
    *,
    entity_type: EntityType,
    candidate: ResolutionCandidate,
    repository: VersionedEntityRepository,  # type: ignore[type-arg]
    source_id: int,
) -> str:
    """Return the canonical entity ID this candidate refers to.

    Matches an existing entity if possible (Strategies 1–3); otherwise
    creates a new one and — if the candidate carried an identifier — attaches
    it as a `Reference`, so the *next* incoming record with the same
    identifier hits Strategy 1 instead of falling through further.
    """
    normalized_name = normalize_name(candidate.name)

    if candidate.identifier_type is not None and candidate.identifier_value:
        existing_id = _find_by_reference(
            session, entity_type, candidate.identifier_type, candidate.identifier_value
        )
        if existing_id is not None:
            return existing_id

    existing_id = _find_by_normalized_name_or_alias(
        session, entity_type, repository, normalized_name
    )
    if existing_id is not None:
        return existing_id

    fuzzy_result = fuzzy_match(session, entity_type, repository, normalized_name)

    if fuzzy_result.outcome == "auto_merge":
        assert fuzzy_result.candidate is not None
        matched_id = fuzzy_result.candidate.entity_id
        # Record the alias so the *next* exact-match lookup (Strategy 2)
        # catches this name directly, without repeating fuzzy matching
        # (ENTITY_RESOLUTION.md Section 6).
        session.add(
            Alias(
                entity_type=entity_type,
                entity_id=matched_id,
                alias_text=candidate.name,
                normalized_alias_text=normalized_name,
                confidence=fuzzy_result.candidate.score,
                source_id=source_id,
            )
        )
        _attach_reference_if_present(session, entity_type, matched_id, candidate, source_id)
        session.flush()
        return matched_id

    # Medium confidence (review) or no match at all: both need a brand-new
    # canonical entity — a medium-confidence candidate is never left
    # unpersisted-and-pending (Section 7).
    entity = repository.create(
        name=candidate.name, normalized_name=normalized_name, source_id=source_id
    )
    _attach_reference_if_present(session, entity_type, entity.id, candidate, source_id)

    if fuzzy_result.outcome == "review":
        assert fuzzy_result.candidate is not None
        session.add(
            EntityResolutionReview(
                entity_type=entity_type,
                candidate_a_id=fuzzy_result.candidate.entity_id,
                candidate_b_id=entity.id,
                confidence_score=fuzzy_result.candidate.score,
                status=ReviewStatus.PENDING,
            )
        )

    session.flush()
    resolved_id: str = entity.id
    return resolved_id
