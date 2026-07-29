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
from ingestion.dailymed.transformer import DailyMedCanonicalCandidate

SaveOutcome = Literal["created", "updated", "unchanged"]


@dataclass(frozen=True)
class SaveResult:
    outcome: SaveOutcome
    product_id: str


def save_spl_document_candidate(
    session: Session, candidate: DailyMedCanonicalCandidate, *, source_id: int
) -> SaveResult:
    """Idempotent upsert keyed on `candidate.natural_key` (SPL `setId`).

    Uses the same `Reference(SPL_SET_ID)` lookup openFDA uses
    (`ingestion/openfda/persistence.py`) — both sources ultimately derive
    from FDA's own SPL corpus and share this identifier space, so a product
    first ingested via one source and later updated via the other lands on
    the *same* canonical Product, each version attributed to whichever
    Source produced it.

    Ingredients and manufacturer are resolved up front (Brick 10:
    `ingestion/common/canonical_save.py` -> `resolution/resolver.py`) —
    ingredients by UNII (DailyMed's IngredientExtractor captures a real
    per-ingredient UNII) or normalized name, manufacturer by DUNS number
    (`manufacturer_duns`, a real authoritative identifier DailyMed exposes
    that openFDA doesn't) or normalized name — so the "did anything change"
    comparison checks resolved IDs, not raw names (see canonical_save.py's
    module docstring for why that distinction matters once resolution is in
    the picture).
    """
    resolved_ingredients = resolve_ingredients(session, candidate.ingredients, source_id)
    manufacturer_id = resolve_manufacturer(
        session,
        candidate.manufacturer_name,
        source_id,
        identifier_type=ReferenceType.DUNS if candidate.manufacturer_duns else None,
        identifier_value=candidate.manufacturer_duns,
    )

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
            and current.dosage_form == candidate.dosage_form
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
            dosage_form=candidate.dosage_form,
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
        dosage_form=candidate.dosage_form,
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
