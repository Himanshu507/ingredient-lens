"""Entity resolution: Strategies 1 and 2 from ENTITY_RESOLUTION.md.

Every incoming Ingredient/Manufacturer candidate is matched against existing
canonical entities, highest-confidence strategy first, before ever creating a
new one:

1. Authoritative identifier exact match (CAS/UNII for ingredients, FDA labeler
   code for manufacturers) — definitive, no confidence score needed (Section 4).
2. Exact match on normalized name or known alias (Section 5).

Fuzzy matching (Strategy 3, manual review queue) is Brick 11 — not here. A
candidate that matches neither strategy becomes a brand-new canonical entity,
never a silent guess.
"""

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.orm import Session

from database.access.versioned_repository import VersionedEntityRepository
from database.models.alias import Alias
from database.models.enums import EntityType, ReferenceType
from database.models.reference import Reference
from normalization.text import normalize_name


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
        .where(version_model.normalized_name == normalized_name)
        .limit(1)
    ).scalar_one_or_none()
    if current_version_match is not None:
        return current_version_match

    alias_match = session.execute(
        sa.select(Alias.entity_id)
        .where(
            Alias.entity_type == entity_type,
            Alias.normalized_alias_text == normalized_name,
        )
        .limit(1)
    ).scalar_one_or_none()
    return alias_match


def resolve_entity(
    session: Session,
    *,
    entity_type: EntityType,
    candidate: ResolutionCandidate,
    repository: VersionedEntityRepository,  # type: ignore[type-arg]
    source_id: int,
) -> str:
    """Return the canonical entity ID this candidate refers to.

    Matches an existing entity if possible (Strategies 1–2); otherwise
    creates a new one and — if the candidate carried an identifier — attaches
    it as a `Reference`, so the *next* incoming record with the same
    identifier hits Strategy 1 instead of falling through to name matching.
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

    entity = repository.create(
        name=candidate.name, normalized_name=normalized_name, source_id=source_id
    )

    if candidate.identifier_type is not None and candidate.identifier_value:
        session.add(
            Reference(
                entity_type=entity_type,
                entity_id=entity.id,
                reference_type=candidate.identifier_type,
                reference_value=candidate.identifier_value,
                source_id=source_id,
            )
        )
        session.flush()

    resolved_id: str = entity.id
    return resolved_id
