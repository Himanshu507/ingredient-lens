"""Query-time retrieval against the canonical model (AI_PIPELINE.md Section 3).

No LLM call here -- this is phase-1 keyword retrieval only, built directly on
top of the search layer (`database.access.search`, Brick 13): the AI layer is
a consumer of that layer, not a second copy of it (ARCHITECTURE.md Section 4).
Retrieval merges hits across all four canonical entity types into a single
ranked, numbered evidence list, carrying full provenance and both confidence
axes described in Section 6:

- `retrieval_confidence` -- how well this result matches the query (`ts_rank`).
- `entity_resolution_confidence` -- how confidently the underlying canonical
  identity was established, when that's relevant. Only ingredient hits can
  carry this today: `search_ingredients` is the only search function that
  matches through an `Alias` (ENTITY_RESOLUTION.md's fuzzy-match path), so
  it's the only place an alias's establishment confidence exists to surface.
  Product/warning/recall hits always carry `None` here, not a fabricated
  value -- their current search implementation has no alias-matching path.

Not in scope here: cross-type score calibration. `ts_rank` values for a
short ingredient name and a long warning body aren't produced from a common
statistical basis, so merging them by raw rank is a rough approximation, not
a calibrated fused score -- acceptable for phase-1 keyword retrieval per
AI_PIPELINE.md Section 3, revisited if/when semantic retrieval (Section 3,
"Future") replaces it.
"""

from dataclasses import dataclass, replace

import sqlalchemy as sa
from sqlalchemy.orm import Session

from database.access.search import (
    ProductHit,
    Provenance,
    RecallHit,
    WarningHit,
    search_ingredients,
    search_products,
    search_recalls,
    search_warnings,
)
from database.models.alias import Alias
from database.models.enums import EntityType


@dataclass(frozen=True)
class Evidence:
    number: int
    entity_type: str
    entity_id: str
    content: str
    retrieval_confidence: float
    entity_resolution_confidence: float | None
    source: Provenance


def _ingredient_resolution_confidence(
    session: Session, ingredient_id: str, tsquery: sa.ColumnElement[str]
) -> float | None:
    confidence = session.execute(
        sa.select(sa.func.max(Alias.confidence)).where(
            Alias.entity_type == EntityType.INGREDIENT,
            Alias.entity_id == ingredient_id,
            Alias.search_vector.op("@@")(tsquery),
        )
    ).scalar_one_or_none()
    return float(confidence) if confidence is not None else None


def _product_content(hit: ProductHit) -> str:
    parts = [hit.name]
    if hit.product_type:
        parts.append(f"Type: {hit.product_type}")
    if hit.dosage_form:
        parts.append(f"Dosage form: {hit.dosage_form}")
    if hit.manufacturer:
        parts.append(f"Manufacturer: {hit.manufacturer.name}")
    if hit.ingredients:
        ingredient_list = ", ".join(f"{i.name} ({i.role})" for i in hit.ingredients)
        parts.append(f"Ingredients: {ingredient_list}")
    if hit.warnings:
        warning_list = "; ".join(f"[{w.category}] {w.text}" for w in hit.warnings)
        parts.append(f"Warnings: {warning_list}")
    if hit.recalls:
        recall_list = "; ".join(
            f"{r.reason} (classification {r.classification}, status {r.status})"
            for r in hit.recalls
        )
        parts.append(f"Recalls: {recall_list}")
    return " | ".join(parts)


def _warning_content(hit: WarningHit) -> str:
    return f"[{hit.category}] {hit.text} (product: {hit.product.name})"


def _recall_content(hit: RecallHit) -> str:
    parts = [
        f"{hit.reason} (classification {hit.classification}, status {hit.status})",
    ]
    if hit.product is not None:
        parts.append(f"Product: {hit.product.name}")
    if hit.manufacturer is not None:
        parts.append(f"Manufacturer: {hit.manufacturer.name}")
    return " | ".join(parts)


def retrieve(session: Session, query: str, *, limit: int = 10) -> list[Evidence]:
    """Top-`limit` evidence items across ingredients, products, warnings, and
    recalls, ranked by retrieval confidence and numbered 1..N for the (not yet
    built) citation step (AI_PIPELINE.md Section 5) to reference unambiguously.
    """
    tsquery = sa.func.plainto_tsquery("english", query)
    candidates: list[Evidence] = []

    for ingredient_hit in search_ingredients(session, query, limit=limit):
        candidates.append(
            Evidence(
                number=0,
                entity_type="ingredient",
                entity_id=ingredient_hit.id,
                content=f"Ingredient: {ingredient_hit.name}",
                retrieval_confidence=ingredient_hit.rank,
                entity_resolution_confidence=_ingredient_resolution_confidence(
                    session, ingredient_hit.id, tsquery
                ),
                source=ingredient_hit.source,
            )
        )

    for product_hit in search_products(session, query, limit=limit):
        candidates.append(
            Evidence(
                number=0,
                entity_type="product",
                entity_id=product_hit.id,
                content=_product_content(product_hit),
                retrieval_confidence=product_hit.rank,
                entity_resolution_confidence=None,
                source=product_hit.source,
            )
        )

    for warning_hit in search_warnings(session, query, limit=limit):
        candidates.append(
            Evidence(
                number=0,
                entity_type="warning",
                entity_id=str(warning_hit.id),
                content=_warning_content(warning_hit),
                retrieval_confidence=warning_hit.rank,
                entity_resolution_confidence=None,
                source=warning_hit.source,
            )
        )

    for recall_hit in search_recalls(session, query, limit=limit):
        candidates.append(
            Evidence(
                number=0,
                entity_type="recall",
                entity_id=str(recall_hit.id),
                content=_recall_content(recall_hit),
                retrieval_confidence=recall_hit.rank,
                entity_resolution_confidence=None,
                source=recall_hit.source,
            )
        )

    candidates.sort(key=lambda e: e.retrieval_confidence, reverse=True)
    top = candidates[:limit]
    return [replace(e, number=i + 1) for i, e in enumerate(top)]
