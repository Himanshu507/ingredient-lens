from dataclasses import dataclass
from typing import Literal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from database.access.ingredients import ingredient_repository
from database.access.manufacturers import manufacturer_repository
from database.access.products import product_repository
from database.models.enums import EntityType, ProductIngredientRole, RecordStatus, ReferenceType
from database.models.product import ProductIngredient
from database.models.reference import Reference
from database.models.warning import Warning
from ingestion.openfda.transformer import DrugLabelCanonicalCandidate

SaveOutcome = Literal["created", "updated", "unchanged"]


@dataclass(frozen=True)
class SaveResult:
    outcome: SaveOutcome
    product_id: str


def _normalize(name: str) -> str:
    return " ".join(name.split()).lower()


def _create_manufacturer(session: Session, name: str | None, source_id: int) -> str | None:
    if not name:
        return None
    manufacturer = manufacturer_repository(session).create(
        name=name, normalized_name=_normalize(name), source_id=source_id
    )
    return manufacturer.id


def _link_ingredients(
    session: Session, product_version_id: int, ingredient_names: tuple[str, ...], source_id: int
) -> None:
    for name in ingredient_names:
        ingredient = ingredient_repository(session).create(
            name=name, normalized_name=_normalize(name), source_id=source_id
        )
        session.add(
            ProductIngredient(
                product_version_id=product_version_id,
                ingredient_id=ingredient.id,
                role=ProductIngredientRole.ACTIVE,
            )
        )
    session.flush()


def _create_warnings(
    session: Session,
    product_id: str,
    warnings: tuple[tuple[str, str], ...],
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


def _find_existing_product_id(session: Session, natural_key: str) -> str | None:
    reference = session.execute(
        sa.select(Reference).where(
            Reference.entity_type == EntityType.PRODUCT,
            Reference.reference_type == ReferenceType.SPL_SET_ID,
            Reference.reference_value == natural_key,
        )
    ).scalar_one_or_none()
    return reference.entity_id if reference is not None else None


def _current_manufacturer_name(session: Session, manufacturer_id: str | None) -> str | None:
    if manufacturer_id is None:
        return None
    manufacturer = manufacturer_repository(session).get_current(manufacturer_id)
    if manufacturer is None or manufacturer.current_version is None:
        return None
    return manufacturer.current_version.name


def _current_ingredient_names(session: Session, product_version_id: int) -> tuple[str, ...]:
    links = session.execute(
        sa.select(ProductIngredient).where(
            ProductIngredient.product_version_id == product_version_id
        )
    ).scalars()
    names = []
    for link in links:
        ingredient = ingredient_repository(session).get_current(link.ingredient_id)
        if ingredient is not None and ingredient.current_version is not None:
            names.append(ingredient.current_version.name)
    return tuple(sorted(names))


def save_drug_label_candidate(
    session: Session, candidate: DrugLabelCanonicalCandidate, *, source_id: int
) -> SaveResult:
    """Idempotent upsert keyed on `candidate.natural_key` (openFDA `set_id`).

    No cross-record entity resolution here (ROADMAP.md Brick 6 — that's
    Brick 10/11): a changed product always gets fresh Manufacturer/Ingredient
    rows, never a match against another product's existing ones. What *is*
    guaranteed is INGESTION_STRATEGY.md Section 4's idempotency invariant for
    a single natural key: unchanged data is a no-op, not a new version, and
    re-running with identical input never creates duplicate rows.
    """
    # Dosage form isn't reliably extractable from openFDA's free-text label
    # sections (no structured field) — left null; DailyMed's SPL XML (Brick 8/9)
    # has a real structured dosage form and will populate this.
    dosage_form = None

    existing_product_id = _find_existing_product_id(session, candidate.natural_key)

    if existing_product_id is not None:
        product = product_repository(session).get_current(existing_product_id)
        assert product is not None and product.current_version is not None
        current = product.current_version

        unchanged = (
            current.name == candidate.product_name
            and current.product_type == candidate.product_type
            and _current_manufacturer_name(session, current.manufacturer_id)
            == candidate.manufacturer_name
            and _current_ingredient_names(session, current.id)
            == tuple(sorted(candidate.ingredient_names))
        )
        if unchanged:
            return SaveResult(outcome="unchanged", product_id=product.id)

        manufacturer_id = _create_manufacturer(session, candidate.manufacturer_name, source_id)
        new_version = product_repository(session).add_version(
            product.id,
            name=candidate.product_name,
            product_type=candidate.product_type,
            dosage_form=dosage_form,
            manufacturer_id=manufacturer_id,
            source_id=source_id,
        )
        _link_ingredients(session, new_version.id, candidate.ingredient_names, source_id)
        _create_warnings(
            session, product.id, candidate.warnings, new_version.version_number, source_id
        )
        return SaveResult(outcome="updated", product_id=product.id)

    manufacturer_id = _create_manufacturer(session, candidate.manufacturer_name, source_id)
    product = product_repository(session).create(
        name=candidate.product_name,
        product_type=candidate.product_type,
        dosage_form=dosage_form,
        manufacturer_id=manufacturer_id,
        source_id=source_id,
    )
    assert product.current_version is not None
    _link_ingredients(session, product.current_version.id, candidate.ingredient_names, source_id)
    _create_warnings(session, product.id, candidate.warnings, 1, source_id)
    session.add(
        Reference(
            entity_type=EntityType.PRODUCT,
            entity_id=product.id,
            reference_type=ReferenceType.SPL_SET_ID,
            reference_value=candidate.natural_key,
            source_id=source_id,
        )
    )
    session.flush()
    return SaveResult(outcome="created", product_id=product.id)
