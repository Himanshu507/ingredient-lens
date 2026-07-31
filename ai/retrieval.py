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
    TsqueryBuilder,
    WarningHit,
    build_tsquery,
    build_tsquery_or,
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
    external_url: str | None


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


# A single product can carry dozens of ingredients and several long warning
# paragraphs -- inlining all of it made one evidence item alone run to
# thousands of characters. That's tolerable for a single fixed evidence
# block (the pre-tool-calling design), but the tool-calling loop
# (ai.answer.ask) can re-fetch and re-render evidence across several tool
# calls in one growing conversation, and a real question hit exactly this:
# openai.BadRequestError, context_length_exceeded, at 150,900 tokens for one
# question. These caps keep each evidence item a bounded-size citation
# snippet, not a full-document dump -- verified against that exact real
# failure (see ai/answer.py's module docstring for the query that triggered
# it).
_MAX_LIST_ITEMS = 8
_MAX_WARNING_CHARS = 220
_MAX_CONTENT_CHARS = 900


def _truncate(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[: max_chars - 1].rstrip() + "…"


def _join_capped(items: list[str], *, max_items: int = _MAX_LIST_ITEMS) -> str:
    if len(items) <= max_items:
        return ", ".join(items)
    shown = items[:max_items]
    return ", ".join(shown) + f", and {len(items) - max_items} more"


def _product_content(hit: ProductHit) -> str:
    parts = [hit.name]
    if hit.product_type:
        parts.append(f"Type: {hit.product_type}")
    if hit.dosage_form:
        parts.append(f"Dosage form: {hit.dosage_form}")
    if hit.manufacturer:
        parts.append(f"Manufacturer: {hit.manufacturer.name}")
    if hit.ingredients:
        ingredient_list = _join_capped([f"{i.name} ({i.role})" for i in hit.ingredients])
        parts.append(f"Ingredients: {ingredient_list}")
    if hit.warnings:
        warning_list = _join_capped(
            [f"[{w.category}] {_truncate(w.text, _MAX_WARNING_CHARS)}" for w in hit.warnings],
            max_items=2,
        )
        parts.append(f"Warnings: {warning_list}")
    if hit.recalls:
        recall_list = _join_capped(
            [
                f"{_truncate(r.reason, _MAX_WARNING_CHARS)} "
                f"(classification {r.classification}, status {r.status})"
                for r in hit.recalls
            ],
            max_items=2,
        )
        parts.append(f"Recalls: {recall_list}")
    return _truncate(" | ".join(parts), _MAX_CONTENT_CHARS)


def _warning_content(hit: WarningHit) -> str:
    text = _truncate(hit.text, _MAX_CONTENT_CHARS)
    return f"[{hit.category}] {text} (product: {hit.product.name})"


def _recall_content(hit: RecallHit) -> str:
    parts = [
        f"{_truncate(hit.reason, _MAX_CONTENT_CHARS)} "
        f"(classification {hit.classification}, status {hit.status})",
    ]
    if hit.product is not None:
        parts.append(f"Product: {hit.product.name}")
    if hit.manufacturer is not None:
        parts.append(f"Manufacturer: {hit.manufacturer.name}")
    return " | ".join(parts)


# Real data has thousands of near-duplicate warnings sharing the same
# boilerplate text across product variants (e.g. ~6,000 acetaminophen
# "liver damage warning" entries vs. ~2,000 distinct NSAID/heart-attack
# warnings). A bare `limit`-sized fetch per entity type returns N copies of
# the single most common boilerplate before a different, still-relevant
# warning ever gets a chance -- fetching a wider pool and deduplicating
# near-identical content (see `_dedup_key`) before truncating to `limit` is
# what actually fixes that, not a bigger `limit` alone (which just returns
# more copies of the same duplicate).
_OVERFETCH_MULTIPLIER = 5


def _dedup_key(entity_type: str, content: str) -> str:
    normalized = " ".join(content.split()).lower()
    return f"{entity_type}:{normalized[:160]}"


def _gather(
    session: Session, query: str, *, limit: int, tsquery_builder: TsqueryBuilder
) -> list[Evidence]:
    tsquery = tsquery_builder(query)
    fetch_limit = limit * _OVERFETCH_MULTIPLIER
    candidates: list[Evidence] = []

    for ingredient_hit in search_ingredients(
        session, query, limit=fetch_limit, tsquery_builder=tsquery_builder
    ):
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
                external_url=None,
            )
        )

    for product_hit in search_products(
        session, query, limit=fetch_limit, tsquery_builder=tsquery_builder
    ):
        candidates.append(
            Evidence(
                number=0,
                entity_type="product",
                entity_id=product_hit.id,
                content=_product_content(product_hit),
                retrieval_confidence=product_hit.rank,
                entity_resolution_confidence=None,
                source=product_hit.source,
                external_url=product_hit.external_url,
            )
        )

    for warning_hit in search_warnings(
        session, query, limit=fetch_limit, tsquery_builder=tsquery_builder
    ):
        candidates.append(
            Evidence(
                number=0,
                entity_type="warning",
                entity_id=str(warning_hit.id),
                content=_warning_content(warning_hit),
                retrieval_confidence=warning_hit.rank,
                entity_resolution_confidence=None,
                source=warning_hit.source,
                external_url=warning_hit.external_url,
            )
        )

    for recall_hit in search_recalls(
        session, query, limit=fetch_limit, tsquery_builder=tsquery_builder
    ):
        candidates.append(
            Evidence(
                number=0,
                entity_type="recall",
                entity_id=str(recall_hit.id),
                content=_recall_content(recall_hit),
                retrieval_confidence=recall_hit.rank,
                entity_resolution_confidence=None,
                source=recall_hit.source,
                external_url=recall_hit.external_url,
            )
        )

    return candidates


def retrieve(session: Session, query: str, *, limit: int = 10) -> list[Evidence]:
    """Top-`limit` evidence items across ingredients, products, warnings, and
    recalls, ranked by retrieval confidence and numbered 1..N for the
    citation step (AI_PIPELINE.md Section 5) to reference unambiguously.

    Tries AND-matching (`build_tsquery`, precise) first. Only if that finds
    *nothing at all* does it retry with OR-matching (`build_tsquery_or`) --
    see that function's docstring for why OR isn't just used as the default
    (it demonstrably outranks precise matches with generic-word noise in
    mixed-field-type merges). This two-step behavior specifically targets
    natural-language-ish questions like "Tell me about the Serious Skincare
    product?", which AND-matching alone answers with zero results even
    though "Serious Skincare" is a clean, specific match on its own.
    """
    candidates = _gather(session, query, limit=limit, tsquery_builder=build_tsquery)
    if not candidates:
        candidates = _gather(session, query, limit=limit, tsquery_builder=build_tsquery_or)

    candidates.sort(key=lambda e: e.retrieval_confidence, reverse=True)

    deduped: list[Evidence] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = _dedup_key(candidate.entity_type, candidate.content)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)

    top = deduped[:limit]
    return [replace(e, number=i + 1) for i, e in enumerate(top)]
