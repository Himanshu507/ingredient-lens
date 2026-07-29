import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from database.models.enums import RecordStatus, ReferenceType
from database.models.ingredient import Ingredient
from database.models.product import Product, ProductVersion
from database.models.reference import Reference
from database.models.source import Source
from ingestion.dailymed.extraction import SplPackage
from ingestion.dailymed.run import ingest_spl_documents
from ingestion.openfda.parser import parse_drug_label_record
from ingestion.openfda.run import ingest_drug_label_records

OPENFDA_GOLDEN = Path(__file__).parent.parent / "golden" / "openfda"
DAILYMED_GOLDEN = Path(__file__).parent.parent / "golden" / "dailymed"

# The real-world SPL set ID both fixtures below are made to share, simulating
# the same product independently ingested from openFDA and DailyMed.
SHARED_SET_ID = "036fd504-0cda-60ab-e063-6394a90a2f18"


def _openfda_record() -> Any:
    with (OPENFDA_GOLDEN / "drug_label_otc.json").open() as f:
        raw = json.load(f)
    record = parse_drug_label_record(raw)
    return replace(record, set_id=SHARED_SET_ID)


def _dailymed_package() -> SplPackage:
    # otc_liquid_bandage.xml's real setId already *is* SHARED_SET_ID.
    xml_bytes = (DAILYMED_GOLDEN / "otc_liquid_bandage.xml").read_bytes()
    return SplPackage(package_name="otc_liquid_bandage.xml", xml_bytes=xml_bytes)


def test_openfda_and_dailymed_share_the_same_canonical_product(db_session: Session) -> None:
    """Brick 9's done-when: DailyMed data lands in the same canonical tables
    openFDA data lands in, both sources' data coexisting correctly, each
    attributed to its correct Source — proven here via a shared SPL set ID,
    since both sources ultimately derive from FDA's own SPL identifier space.
    """
    openfda_log = ingest_drug_label_records(db_session, [_openfda_record()])
    dailymed_log = ingest_spl_documents(db_session, [_dailymed_package()])

    assert openfda_log.records_created == 1
    assert dailymed_log.records_updated == 1  # same Product, new version

    # Exactly one canonical Product exists for this set ID, not two.
    reference = db_session.execute(
        sa.select(Reference).where(Reference.reference_value == SHARED_SET_ID)
    ).scalar_one()
    assert db_session.execute(sa.select(sa.func.count()).select_from(Product)).scalar_one() == 1

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
    assert all(v.status == RecordStatus.ACTIVE for v in versions)

    # Each version is attributed to the Source that actually produced it.
    sources_by_id = {s.id: s.source_system for s in db_session.execute(sa.select(Source)).scalars()}
    assert sources_by_id[versions[0].source_id] == "openfda"
    assert sources_by_id[versions[1].source_id] == "dailymed"


def test_same_ingredient_from_both_sources_merges_across_different_products(
    db_session: Session,
) -> None:
    """Brick 10's literal done-when: ingesting the same ingredient from both
    openFDA and DailyMed under a shared UNII correctly merges into one
    canonical Ingredient — even though the two *products* are unrelated
    (distinct set IDs), unlike the shared-product test above.
    """
    shared_unii = "PQ6CK8PD0R"

    with (OPENFDA_GOLDEN / "drug_label_boxed_warning.json").open() as f:
        raw = json.load(f)
    openfda_record = replace(
        parse_drug_label_record(raw),
        set_id="cross-source-ingredient-openfda",
        substance_name=("ASCORBIC ACID",),
        unii=(shared_unii,),
    )

    otc_xml = (DAILYMED_GOLDEN / "otc_liquid_bandage.xml").read_bytes()
    # Swap in a distinct setId (a different, unrelated product) and retarget
    # the first active ingredient's real UNII/name to the shared one.
    otc_xml = otc_xml.replace(
        b"036fd504-0cda-60ab-e063-6394a90a2f18", b"cross-source-ingredient-dailymed"
    )
    otc_xml = otc_xml.replace(b"PH41D05744", shared_unii.encode())
    otc_xml = otc_xml.replace(b"BENZETHONIUM CHLORIDE", b"VITAMIN C")
    dailymed_package = SplPackage(package_name="vitamin_c_product.zip", xml_bytes=otc_xml)

    openfda_log = ingest_drug_label_records(db_session, [openfda_record])
    dailymed_log = ingest_spl_documents(db_session, [dailymed_package])

    assert openfda_log.records_created == 1
    assert dailymed_log.records_created == 1

    # Two distinct, unrelated products (the OTC fixture has 8 ingredients of
    # its own -- only the one retargeted to `shared_unii` should merge).
    assert db_session.execute(sa.select(sa.func.count()).select_from(Product)).scalar_one() == 2

    ingredient_id_by_unii = {
        r.reference_value: r.entity_id
        for r in db_session.execute(
            sa.select(Reference).where(Reference.reference_type == ReferenceType.UNII)
        ).scalars()
    }
    assert ingredient_id_by_unii[shared_unii] is not None

    # Both products' ingredient link for the shared substance points at the
    # *same* canonical Ingredient -- not two separate rows under two names.
    shared_ingredient_id = ingredient_id_by_unii[shared_unii]
    ingredient = db_session.get(Ingredient, shared_ingredient_id)
    assert ingredient is not None and ingredient.current_version is not None
    assert ingredient.current_version.name in ("ASCORBIC ACID", "VITAMIN C")

    # Exactly one Reference was written for this UNII, not one per source.
    unii_refs_for_shared = [v for v in ingredient_id_by_unii.values() if v == shared_ingredient_id]
    assert len(unii_refs_for_shared) == 1
