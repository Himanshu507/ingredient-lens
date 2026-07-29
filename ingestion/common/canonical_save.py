"""Shared save-path helpers used by every source's persistence layer.

The identity/version mechanic itself lives in database/access/ (Brick 3);
this module is the layer above it that both openFDA (Brick 6) and DailyMed
(Brick 9) share for the parts of "save a product" that don't depend on a
source's specific field shapes: attaching a natural-key Reference,
resolving Manufacturer/Ingredient rows against existing canonical entities
(Brick 10 — resolution/resolver.py), and reading back current linked state
to decide whether anything actually changed.

Resolution happens up front, before the "did anything change" comparison —
not only in the branch that turns out to need an update. This matters once
resolution is in the picture: two products can share one canonical
Ingredient under different raw spellings (e.g. "WATER" vs "Purified Water",
same UNII), so comparing *names* would report "changed" on every re-run for
whichever product didn't happen to create that entity first. Comparing
resolved IDs is what actually reflects "did this product's linked entities
change," and is safe to compute unconditionally: resolving an
already-existing entity is a read, not a write.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.orm import Session

from database.access.ingredients import ingredient_repository
from database.access.manufacturers import manufacturer_repository
from database.models.enums import (
    EntityType,
    ProductIngredientRole,
    RecordStatus,
    ReferenceType,
    WarningCategory,
)
from database.models.product import ProductIngredient
from database.models.reference import Reference
from database.models.warning import Warning
from ingestion.common.ingredient_link import IngredientLink
from resolution.resolver import ResolutionCandidate, resolve_entity


def find_product_id_by_reference(
    session: Session, *, reference_type: ReferenceType, reference_value: str
) -> str | None:
    """Look up a canonical Product by natural key (never a freshly generated ID).

    openFDA and DailyMed both ultimately derive from FDA's own SPL corpus and
    share the same `set_id` identifier space — using the same
    `ReferenceType.SPL_SET_ID` lookup for both means a product ingested first
    by one source and later updated by the other lands on the *same*
    canonical Product. Products are matched by this natural key alone —
    ENTITY_RESOLUTION.md's semantic resolution pipeline applies to
    Ingredient/Manufacturer (below), not Product.
    """
    reference = session.execute(
        sa.select(Reference).where(
            Reference.entity_type == EntityType.PRODUCT,
            Reference.reference_type == reference_type,
            Reference.reference_value == reference_value,
        )
    ).scalar_one_or_none()
    return reference.entity_id if reference is not None else None


def resolve_manufacturer(
    session: Session,
    name: str | None,
    source_id: int,
    *,
    identifier_type: ReferenceType | None = None,
    identifier_value: str | None = None,
) -> str | None:
    """Resolve (or create) a canonical Manufacturer — ENTITY_RESOLUTION.md Section 8."""
    if not name:
        return None
    candidate = ResolutionCandidate(
        name=name, identifier_type=identifier_type, identifier_value=identifier_value
    )
    return resolve_entity(
        session,
        entity_type=EntityType.MANUFACTURER,
        candidate=candidate,
        repository=manufacturer_repository(session),
        source_id=source_id,
    )


def resolve_ingredients(
    session: Session, ingredients: Sequence[IngredientLink], source_id: int
) -> tuple[tuple[str, ProductIngredientRole], ...]:
    """Resolve every ingredient to a canonical Ingredient ID (Brick 10:
    ENTITY_RESOLUTION.md Strategies 1–2), deduplicated by resolved identity.

    Some real SPL documents legitimately list the same substance more than
    once (e.g. a multi-part kit repeating a shared diluent per component —
    confirmed against real DailyMed data: 27 of 169 documents in one sample
    export). Once resolved, repeated mentions collapse to the same canonical
    ID; `product_ingredients` has one row per (product_version, ingredient),
    not per source mention, so the first occurrence's role wins and later
    duplicates are dropped here rather than causing a primary-key conflict
    at insert time.

    Returns a sorted `(ingredient_id, role)` tuple — this is both what gets
    persisted (via `link_resolved_ingredients`) and what the "did anything
    change" comparison in persistence.py checks against, so the two stay in
    sync by construction.
    """
    seen_ids: set[str] = set()
    result: list[tuple[str, ProductIngredientRole]] = []
    for link in ingredients:
        candidate = ResolutionCandidate(
            name=link.name,
            identifier_type=ReferenceType.UNII if link.unii else None,
            identifier_value=link.unii,
        )
        ingredient_id = resolve_entity(
            session,
            entity_type=EntityType.INGREDIENT,
            candidate=candidate,
            repository=ingredient_repository(session),
            source_id=source_id,
        )
        if ingredient_id in seen_ids:
            continue
        seen_ids.add(ingredient_id)
        result.append((ingredient_id, link.role))
    return tuple(sorted(result))


def link_resolved_ingredients(
    session: Session,
    product_version_id: int,
    resolved_ingredients: Sequence[tuple[str, ProductIngredientRole]],
) -> None:
    """Persist already-resolved `(ingredient_id, role)` pairs — see `resolve_ingredients`."""
    for ingredient_id, role in resolved_ingredients:
        session.add(
            ProductIngredient(
                product_version_id=product_version_id, ingredient_id=ingredient_id, role=role
            )
        )
    session.flush()


def current_ingredients_with_roles(
    session: Session, product_version_id: int
) -> tuple[tuple[str, ProductIngredientRole], ...]:
    """The currently-linked `(ingredient_id, role)` pairs for a product version —
    directly from `product_ingredients`, not by name, so it compares like-for-like
    against `resolve_ingredients`' output regardless of which product first
    created any shared canonical Ingredient.
    """
    links = session.execute(
        sa.select(ProductIngredient).where(
            ProductIngredient.product_version_id == product_version_id
        )
    ).scalars()
    return tuple(sorted((link.ingredient_id, link.role) for link in links))


def create_warnings(
    session: Session,
    product_id: str,
    warnings: Sequence[tuple[WarningCategory, str]],
    version_number: int,
    source_id: int,
) -> None:
    for category, text in warnings:
        session.add(
            Warning(
                product_id=product_id,
                category=category,
                text=text,
                status=RecordStatus.ACTIVE,
                version_number=version_number,
                source_id=source_id,
            )
        )
    session.flush()


def current_warnings(
    session: Session, product_id: str, version_number: int
) -> tuple[tuple[WarningCategory, str], ...]:
    warnings = session.execute(
        sa.select(Warning).where(
            Warning.product_id == product_id, Warning.version_number == version_number
        )
    ).scalars()
    return tuple(sorted((w.category, w.text) for w in warnings))
