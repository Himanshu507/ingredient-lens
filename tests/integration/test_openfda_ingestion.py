import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from database.models.enums import IngestionRunStatus
from database.models.ingredient import Ingredient
from database.models.manufacturer import Manufacturer
from database.models.product import Product, ProductVersion
from database.models.reference import Reference
from database.models.warning import Warning
from ingestion.openfda.parser import parse_drug_label_record
from ingestion.openfda.run import ingest_drug_label_records

GOLDEN_DIR = Path(__file__).parent.parent / "golden" / "openfda"


def _load(name: str) -> dict[str, Any]:
    with (GOLDEN_DIR / name).open() as f:
        result: dict[str, Any] = json.load(f)
        return result


def _load_records() -> list[Any]:
    return [
        parse_drug_label_record(_load("drug_label_otc.json")),
        parse_drug_label_record(_load("drug_label_boxed_warning.json")),
    ]


def _count(session: Session, model: type) -> int:
    return session.execute(sa.select(sa.func.count()).select_from(model)).scalar_one()


def test_ingest_creates_canonical_records_and_logs_the_run(db_session: Session) -> None:
    log = ingest_drug_label_records(db_session, _load_records())

    assert log.status == IngestionRunStatus.COMPLETED
    assert log.records_fetched == 2
    assert log.records_validated == 2
    assert log.records_created == 2
    assert log.records_updated == 0
    assert log.records_unchanged == 0
    assert log.records_rejected == 0

    assert _count(db_session, Product) == 2
    assert _count(db_session, Manufacturer) == 2
    assert _count(db_session, Ingredient) == 2  # one substance each
    # 2 SPL_SET_ID refs (one per product) + 2 UNII refs (one per ingredient,
    # both fixtures' single substance carries a UNII) -- entity resolution
    # (Brick 10) attaches an identifier Reference to every newly created
    # Ingredient/Manufacturer that has one, not just to Products.
    assert _count(db_session, Reference) == 4
    assert _count(db_session, Warning) >= 2  # at least one warning/boxed_warning each


def test_reingesting_identical_data_produces_zero_duplicates(db_session: Session) -> None:
    ingest_drug_label_records(db_session, _load_records())
    products_after_first = _count(db_session, Product)
    manufacturers_after_first = _count(db_session, Manufacturer)
    ingredients_after_first = _count(db_session, Ingredient)
    warnings_after_first = _count(db_session, Warning)

    second_log = ingest_drug_label_records(db_session, _load_records())

    assert second_log.records_created == 0
    assert second_log.records_updated == 0
    assert second_log.records_unchanged == 2

    assert _count(db_session, Product) == products_after_first
    assert _count(db_session, Manufacturer) == manufacturers_after_first
    assert _count(db_session, Ingredient) == ingredients_after_first
    assert _count(db_session, Warning) == warnings_after_first


def test_changed_record_creates_new_version_not_new_product(db_session: Session) -> None:
    ingest_drug_label_records(db_session, _load_records())
    products_after_first = _count(db_session, Product)

    original_otc, boxed = _load_records()
    changed_otc = replace(original_otc, brand_name="SILICEA (reformulated)")

    log = ingest_drug_label_records(db_session, [changed_otc, boxed])

    assert log.records_updated == 1
    assert log.records_unchanged == 1
    assert log.records_created == 0
    assert _count(db_session, Product) == products_after_first  # no new Product row

    reference = db_session.execute(
        sa.select(Reference).where(Reference.reference_value == original_otc.set_id)
    ).scalar_one()
    versions = (
        db_session.execute(
            sa.select(ProductVersion)
            .where(ProductVersion.product_id == reference.entity_id)
            .order_by(ProductVersion.version_number)
        )
        .scalars()
        .all()
    )
    assert len(versions) == 2
    assert versions[0].name == "SILICEA"
    assert versions[1].name == "SILICEA (reformulated)"


def test_invalid_record_is_rejected_not_persisted(db_session: Session) -> None:
    otc, _ = _load_records()
    unusable = replace(otc, brand_name=None, generic_name=None, set_id="rejected-record")

    log = ingest_drug_label_records(db_session, [unusable])

    assert log.records_fetched == 1
    assert log.records_rejected == 1
    assert log.records_created == 0

    assert (
        db_session.execute(
            sa.select(Reference).where(Reference.reference_value == "rejected-record")
        ).scalar_one_or_none()
        is None
    )
