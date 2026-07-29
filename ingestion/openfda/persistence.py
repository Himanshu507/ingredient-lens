from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from database.access.products import product_repository
from database.models.enums import EntityType, ReferenceType
from database.models.reference import Reference
from ingestion.common.canonical_save import (
    create_warnings,
    current_ingredients_with_roles,
    current_warnings,
    find_product_id_by_reference,
    link_resolved_ingredients,
    resolve_ingredients,
    resolve_manufacturer,
)
from ingestion.openfda.transformer import DrugLabelCanonicalCandidate

SaveOutcome = Literal["created", "updated", "unchanged"]


@dataclass(frozen=True)
class SaveResult:
    outcome: SaveOutcome
    product_id: str


def save_drug_label_candidate(
    session: Session, candidate: DrugLabelCanonicalCandidate, *, source_id: int
) -> SaveResult:
    """Idempotent upsert keyed on `candidate.natural_key` (openFDA `set_id`).

    Products are matched by this natural key alone — no semantic resolution
    for products (ROADMAP.md Brick 6/9). Ingredients and manufacturers *do*
    go through entity resolution as of Brick 10
    (`ingestion/common/canonical_save.py` -> `resolution/resolver.py`),
    resolved up front so the "did anything change" comparison below checks
    resolved IDs, not raw names (see canonical_save.py's module docstring
    for why that distinction matters once resolution is in the picture).

    openFDA doesn't expose a manufacturer-specific authoritative identifier
    (no labeler code in `openfda` metadata) — manufacturer resolution here is
    name-only (Strategy 2). DailyMed's adapter (Brick 9/10) has a real DUNS
    number and uses Strategy 1.
    """
    dosage_form = None  # see DosageExtractor's docstring for why openFDA can't populate this

    resolved_ingredients = resolve_ingredients(session, candidate.ingredients, source_id)
    manufacturer_id = resolve_manufacturer(session, candidate.manufacturer_name, source_id)

    existing_product_id = find_product_id_by_reference(
        session, reference_type=ReferenceType.SPL_SET_ID, reference_value=candidate.natural_key
    )

    if existing_product_id is not None:
        product = product_repository(session).get_current(existing_product_id)
        assert product is not None and product.current_version is not None
        current = product.current_version

        unchanged = (
            current.name == candidate.product_name
            and current.product_type == candidate.product_type
            and current.manufacturer_id == manufacturer_id
            and current_ingredients_with_roles(session, current.id) == resolved_ingredients
            and current_warnings(session, product.id, current.version_number)
            == tuple(sorted(candidate.warnings))
        )
        if unchanged:
            return SaveResult(outcome="unchanged", product_id=product.id)

        new_version = product_repository(session).add_version(
            product.id,
            name=candidate.product_name,
            product_type=candidate.product_type,
            dosage_form=dosage_form,
            manufacturer_id=manufacturer_id,
            source_id=source_id,
        )
        link_resolved_ingredients(session, new_version.id, resolved_ingredients)
        create_warnings(
            session, product.id, candidate.warnings, new_version.version_number, source_id
        )
        return SaveResult(outcome="updated", product_id=product.id)

    product = product_repository(session).create(
        name=candidate.product_name,
        product_type=candidate.product_type,
        dosage_form=dosage_form,
        manufacturer_id=manufacturer_id,
        source_id=source_id,
    )
    assert product.current_version is not None
    link_resolved_ingredients(session, product.current_version.id, resolved_ingredients)
    create_warnings(session, product.id, candidate.warnings, 1, source_id)
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
