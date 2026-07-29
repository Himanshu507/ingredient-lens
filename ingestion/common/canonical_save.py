"""Shared save-path helpers used by every source's persistence layer.

The identity/version mechanic itself lives in database/access/ (Brick 3);
this module is the layer above it that both openFDA (Brick 6) and DailyMed
(Brick 9) share for the parts of "save a product" that don't depend on a
source's specific field shapes: attaching a natural-key Reference, creating
Manufacturer/Ingredient rows, and reading back current linked state to decide
whether anything actually changed.
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


def normalize_name(name: str) -> str:
    return " ".join(name.split()).lower()


def find_product_id_by_reference(
    session: Session, *, reference_type: ReferenceType, reference_value: str
) -> str | None:
    """Look up a canonical Product by natural key (never a freshly generated ID).

    openFDA and DailyMed both ultimately derive from FDA's own SPL corpus and
    share the same `set_id` identifier space — using the same
    `ReferenceType.SPL_SET_ID` lookup for both means a product ingested first
    by one source and later updated by the other lands on the *same*
    canonical Product, with no entity resolution required for this case.
    """
    reference = session.execute(
        sa.select(Reference).where(
            Reference.entity_type == EntityType.PRODUCT,
            Reference.reference_type == reference_type,
            Reference.reference_value == reference_value,
        )
    ).scalar_one_or_none()
    return reference.entity_id if reference is not None else None


def create_manufacturer(session: Session, name: str | None, source_id: int) -> str | None:
    if not name:
        return None
    manufacturer = manufacturer_repository(session).create(
        name=name, normalized_name=normalize_name(name), source_id=source_id
    )
    return manufacturer.id


def current_manufacturer_name(session: Session, manufacturer_id: str | None) -> str | None:
    if manufacturer_id is None:
        return None
    manufacturer = manufacturer_repository(session).get_current(manufacturer_id)
    if manufacturer is None or manufacturer.current_version is None:
        return None
    return manufacturer.current_version.name


def link_ingredients(
    session: Session,
    product_version_id: int,
    ingredients: Sequence[tuple[str, ProductIngredientRole]],
    source_id: int,
) -> None:
    for name, role in ingredients:
        ingredient = ingredient_repository(session).create(
            name=name, normalized_name=normalize_name(name), source_id=source_id
        )
        session.add(
            ProductIngredient(
                product_version_id=product_version_id, ingredient_id=ingredient.id, role=role
            )
        )
    session.flush()


def current_ingredients_with_roles(
    session: Session, product_version_id: int
) -> tuple[tuple[str, ProductIngredientRole], ...]:
    links = session.execute(
        sa.select(ProductIngredient).where(
            ProductIngredient.product_version_id == product_version_id
        )
    ).scalars()
    result = []
    for link in links:
        ingredient = ingredient_repository(session).get_current(link.ingredient_id)
        if ingredient is not None and ingredient.current_version is not None:
            result.append((ingredient.current_version.name, link.role))
    return tuple(sorted(result))


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
