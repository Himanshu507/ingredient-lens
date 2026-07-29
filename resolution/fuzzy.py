"""Strategy 3: fuzzy matching (ENTITY_RESOLUTION.md Section 6).

Only reached when Strategies 1–2 (resolver.py) find nothing — no
authoritative identifier, no exact normalized-name/alias match. Trigram
similarity (`pg_trgm`) generates candidates cheaply from "every ingredient
in the database" down to a handful of plausible ones; the best candidate's
score is routed by a three-tier threshold:

    score >= HIGH_CONFIDENCE_THRESHOLD    -> auto-merge (alias recorded)
    MEDIUM <= score < HIGH                 -> manual review queue (Section 7)
    score <  MEDIUM_CONFIDENCE_THRESHOLD   -> no match, caller creates new entity

Thresholds are a tuned parameter, not an architectural commitment (Section 6)
— these defaults match the doc's own illustrative values. Note: trigram
similarity cannot bridge substitution-type synonyms that share no
substring at all (e.g. "vitamin c" / "ascorbic acid" scores exactly 0.0,
verified against real data) — that class of match is what Strategy 1
(shared UNII, Brick 10) or a future curated synonym dictionary are for, not
this strategy. Conflating the two would mean loosening thresholds so far
that unrelated substances start merging (Section 1's central warning).
"""

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.orm import Session

from database.access.versioned_repository import VersionedEntityRepository
from database.models.alias import Alias
from database.models.enums import EntityType, RecordStatus

HIGH_CONFIDENCE_THRESHOLD = 0.92
MEDIUM_CONFIDENCE_THRESHOLD = 0.75
MAX_CANDIDATES = 5


@dataclass(frozen=True)
class FuzzyCandidate:
    entity_id: str
    matched_text: str
    score: float


def generate_candidates(
    session: Session,
    entity_type: EntityType,
    repository: VersionedEntityRepository,  # type: ignore[type-arg]
    normalized_name: str,
    *,
    limit: int = MAX_CANDIDATES,
) -> list[FuzzyCandidate]:
    """Trigram-similarity candidates from current canonical names and
    aliases, highest similarity first — one entry per entity (its best-scoring
    name/alias match), not one per matched string.
    """
    identity_model = repository.identity_model
    version_model = repository.version_model

    name_rows = session.execute(
        sa.select(
            identity_model.id,
            version_model.normalized_name,
            sa.func.similarity(version_model.normalized_name, normalized_name).label("score"),
        )
        .join(version_model, version_model.id == identity_model.current_version_id)
        .where(
            sa.func.similarity(version_model.normalized_name, normalized_name) > 0,
            version_model.status == RecordStatus.ACTIVE,
        )
        .order_by(sa.desc("score"))
        .limit(limit)
    ).all()

    alias_rows = session.execute(
        sa.select(
            Alias.entity_id,
            Alias.normalized_alias_text,
            sa.func.similarity(Alias.normalized_alias_text, normalized_name).label("score"),
        )
        .where(
            Alias.entity_type == entity_type,
            sa.func.similarity(Alias.normalized_alias_text, normalized_name) > 0,
        )
        .order_by(sa.desc("score"))
        .limit(limit)
    ).all()

    best_by_entity: dict[str, FuzzyCandidate] = {}
    for entity_id, matched_text, score in (*name_rows, *alias_rows):
        candidate = FuzzyCandidate(
            entity_id=entity_id, matched_text=matched_text, score=float(score)
        )
        existing = best_by_entity.get(entity_id)
        if existing is None or candidate.score > existing.score:
            best_by_entity[entity_id] = candidate

    return sorted(best_by_entity.values(), key=lambda c: c.score, reverse=True)[:limit]


@dataclass(frozen=True)
class FuzzyMatchResult:
    outcome: str  # "auto_merge" | "review" | "no_match"
    candidate: FuzzyCandidate | None


def fuzzy_match(
    session: Session,
    entity_type: EntityType,
    repository: VersionedEntityRepository,  # type: ignore[type-arg]
    normalized_name: str,
) -> FuzzyMatchResult:
    candidates = generate_candidates(session, entity_type, repository, normalized_name)
    if not candidates:
        return FuzzyMatchResult(outcome="no_match", candidate=None)

    best = candidates[0]
    if best.score >= HIGH_CONFIDENCE_THRESHOLD:
        return FuzzyMatchResult(outcome="auto_merge", candidate=best)
    if best.score >= MEDIUM_CONFIDENCE_THRESHOLD:
        return FuzzyMatchResult(outcome="review", candidate=best)
    return FuzzyMatchResult(outcome="no_match", candidate=None)
