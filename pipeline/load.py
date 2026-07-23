"""Stage 4 — structured, normalized rows -> queryable Postgres schema.

Deep module: load_normalized() hides the upsert-by-name logic that makes
re-running idempotent (no duplicate ingredients/statuses on a second run).
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Ingredient, IngredientRegulatoryStatus
from db.session import get_session
from pipeline.normalize import NormalizedIngredient

log = logging.getLogger(__name__)


def _upsert(session: Session, row: NormalizedIngredient) -> None:
    ingredient = session.execute(
        select(Ingredient).where(Ingredient.name == row.ingredient_name)
    ).scalar_one_or_none()

    if ingredient is None:
        ingredient = Ingredient(name=row.ingredient_name, synonyms=row.synonyms)
        session.add(ingredient)
        session.flush()
    else:
        ingredient.synonyms = row.synonyms

    status = session.execute(
        select(IngredientRegulatoryStatus).where(
            IngredientRegulatoryStatus.ingredient_id == ingredient.id,
            IngredientRegulatoryStatus.country_id == "US",
        )
    ).scalar_one_or_none()

    if status is None:
        status = IngredientRegulatoryStatus(ingredient_id=ingredient.id, country_id="US")
        session.add(status)

    citation = row.actions[0] if row.actions else None

    status.normalized_status = row.normalized_status
    status.category_codes = row.category_codes
    status.reasoning = row.reasoning
    status.confidence = row.confidence
    status.needs_review = row.needs_review
    status.citation_url = citation.url if citation else None
    status.citation_text = citation.text if citation else None
    status.date_added = row.date_added
    status.source_staging_id = row.source_staging_id


def load_normalized(rows: list[NormalizedIngredient]) -> None:
    with get_session() as session:
        for row in rows:
            _upsert(session, row)
    log.info("loaded %d ingredients into DB", len(rows))
