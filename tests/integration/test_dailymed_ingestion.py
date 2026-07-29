from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import Session

from database.models.enums import IngestionRunStatus
from database.models.ingredient import Ingredient
from database.models.manufacturer import Manufacturer
from database.models.product import Product, ProductVersion
from database.models.reference import Reference
from database.models.warning import Warning
from ingestion.dailymed.extraction import SplPackage
from ingestion.dailymed.run import ingest_spl_documents

GOLDEN_DIR = Path(__file__).parent.parent / "golden" / "dailymed"


def _package(name: str) -> SplPackage:
    return SplPackage(package_name=name, xml_bytes=(GOLDEN_DIR / name).read_bytes())


def _three_real_packages() -> list[SplPackage]:
    return [
        _package("animal_injection.xml"),
        _package("human_rx_injection.xml"),
        _package("otc_liquid_bandage.xml"),
    ]


def _count(session: Session, model: type) -> int:
    return session.execute(sa.select(sa.func.count()).select_from(model)).scalar_one()


def test_ingest_creates_canonical_records_and_logs_the_run(db_session: Session) -> None:
    log = ingest_spl_documents(db_session, _three_real_packages())

    assert log.status == IngestionRunStatus.COMPLETED
    assert log.records_fetched == 3
    assert log.records_validated == 3
    assert log.records_created == 3
    assert log.records_rejected == 0

    assert _count(db_session, Product) == 3
    assert _count(db_session, Manufacturer) == 3
    assert _count(db_session, Ingredient) == 1 + 5 + 8  # animal, human_rx, otc
    # 3 SPL_SET_ID refs (one per product) + 14 UNII refs (every one of the
    # 1+5+8 ingredients across all three real documents carries a UNII) +
    # 3 DUNS refs (every manufacturer carries one) -- entity resolution
    # (Brick 10) attaches an identifier Reference to every newly created
    # Ingredient/Manufacturer that has one, not just to Products.
    assert _count(db_session, Reference) == 3 + 14 + 3
    assert _count(db_session, Warning) >= 3


def test_reingesting_identical_data_produces_zero_duplicates(db_session: Session) -> None:
    ingest_spl_documents(db_session, _three_real_packages())
    products_after_first = _count(db_session, Product)
    manufacturers_after_first = _count(db_session, Manufacturer)
    ingredients_after_first = _count(db_session, Ingredient)
    warnings_after_first = _count(db_session, Warning)

    second_log = ingest_spl_documents(db_session, _three_real_packages())

    assert second_log.records_created == 0
    assert second_log.records_updated == 0
    assert second_log.records_unchanged == 3

    assert _count(db_session, Product) == products_after_first
    assert _count(db_session, Manufacturer) == manufacturers_after_first
    assert _count(db_session, Ingredient) == ingredients_after_first
    assert _count(db_session, Warning) == warnings_after_first


def test_changed_document_creates_new_version_not_new_product(db_session: Session) -> None:
    ingest_spl_documents(db_session, _three_real_packages())
    products_after_first = _count(db_session, Product)

    otc_xml = (GOLDEN_DIR / "otc_liquid_bandage.xml").read_bytes()
    changed_xml = otc_xml.replace(b"Liquid Bandage", b"Liquid Bandage Extra Strength")
    changed_package = SplPackage(package_name="otc_liquid_bandage.xml", xml_bytes=changed_xml)

    animal, human_rx, _ = _three_real_packages()
    log = ingest_spl_documents(db_session, [animal, human_rx, changed_package])

    assert log.records_updated == 1
    assert log.records_unchanged == 2
    assert log.records_created == 0
    assert _count(db_session, Product) == products_after_first

    reference = db_session.execute(
        sa.select(Reference).where(
            Reference.reference_value == "036fd504-0cda-60ab-e063-6394a90a2f18"
        )
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
    assert versions[0].name == "Liquid Bandage"
    assert versions[1].name == "Liquid Bandage Extra Strength"


def test_document_missing_ingredients_is_rejected(db_session: Session) -> None:
    log = ingest_spl_documents(db_session, [_package("no_ingredients_section.xml")])

    assert log.records_fetched == 1
    assert log.records_rejected == 1
    assert log.records_created == 0
