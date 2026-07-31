from datetime import UTC, datetime

from sqlalchemy.orm import Session

from database.access.ingredients import ingredient_repository
from database.access.manufacturers import manufacturer_repository
from database.access.products import product_repository
from database.access.search import (
    search_ingredients,
    search_products,
    search_recalls,
    search_warnings,
)
from database.models.alias import Alias
from database.models.enums import (
    EntityType,
    ProductIngredientRole,
    RecallClassification,
    RecallStatus,
    RecordStatus,
    ReferenceType,
    WarningCategory,
)
from database.models.product import ProductIngredient
from database.models.recall import Recall
from database.models.reference import Reference
from database.models.source import Source
from database.models.warning import Warning


def _make_source(session: Session) -> int:
    source = Source(
        source_system="test",
        endpoint_or_document_type="unit-test-fixture",
        ingestion_run_id="run-1",
        ingested_at=datetime.now(UTC),
    )
    session.add(source)
    session.flush()
    return source.id


def test_search_ingredients_finds_canonical_entity_via_known_alias(db_session: Session) -> None:
    """Brick 13's literal done-when: a keyword search for "Vitamin C" must
    find canonical "Ascorbic Acid" -- the alias relationship established by
    entity resolution (ENTITY_RESOLUTION.md) is what makes this possible;
    searching the canonical name alone would not."""
    source_id = _make_source(db_session)
    ingredient = ingredient_repository(db_session).create(
        name="Ascorbic Acid", normalized_name="ascorbic acid", source_id=source_id
    )
    db_session.add(
        Alias(
            entity_type=EntityType.INGREDIENT,
            entity_id=ingredient.id,
            alias_text="Vitamin C",
            normalized_alias_text="vitamin c",
            confidence=1.0,
            source_id=source_id,
        )
    )
    db_session.flush()

    hits = search_ingredients(db_session, "vitamin c")

    assert len(hits) == 1
    assert hits[0].id == ingredient.id
    assert hits[0].name == "Ascorbic Acid"  # the canonical name, not the alias
    assert hits[0].source.source_system == "test"


def test_search_ingredients_matches_canonical_name_directly_too(db_session: Session) -> None:
    source_id = _make_source(db_session)
    ingredient_repository(db_session).create(
        name="Naproxen", normalized_name="naproxen", source_id=source_id
    )
    db_session.flush()

    hits = search_ingredients(db_session, "naproxen")

    assert len(hits) == 1
    assert hits[0].name == "Naproxen"


def test_search_ingredients_no_match_returns_empty(db_session: Session) -> None:
    source_id = _make_source(db_session)
    ingredient_repository(db_session).create(
        name="Naproxen", normalized_name="naproxen", source_id=source_id
    )
    db_session.flush()

    assert search_ingredients(db_session, "acetaminophen") == []


def test_search_products_returns_full_provenance_and_associations(db_session: Session) -> None:
    """A search hit carries its ingredients, manufacturer, warnings, and
    recalls, each traceable back to a Source (ROADMAP.md Brick 13's
    "correct provenance attached to each result")."""
    source_id = _make_source(db_session)
    manufacturer = manufacturer_repository(db_session).create(
        name="Acme Pharma", normalized_name="acme pharma", source_id=source_id
    )
    ingredient = ingredient_repository(db_session).create(
        name="Ascorbic Acid", normalized_name="ascorbic acid", source_id=source_id
    )
    product = product_repository(db_session).create(
        name="Vitamin C Tablets",
        product_type="dietary supplement",
        dosage_form="tablet",
        manufacturer_id=manufacturer.id,
        source_id=source_id,
    )
    assert product.current_version is not None
    db_session.add(
        ProductIngredient(
            product_version_id=product.current_version.id,
            ingredient_id=ingredient.id,
            role=ProductIngredientRole.ACTIVE,
        )
    )
    db_session.add(
        Warning(
            product_id=product.id,
            category=WarningCategory.PRECAUTION,
            text="Do not exceed the recommended daily dose",
            status=RecordStatus.ACTIVE,
            version_number=1,
            source_id=source_id,
        )
    )
    db_session.add(
        Recall(
            product_id=product.id,
            manufacturer_id=manufacturer.id,
            reason="Possible contamination found in tablets",
            classification=RecallClassification.CLASS_II,
            status=RecallStatus.ONGOING,
            source_id=source_id,
        )
    )
    db_session.flush()

    hits = search_products(db_session, "vitamin c tablets")

    assert len(hits) == 1
    hit = hits[0]
    assert hit.id == product.id
    assert hit.manufacturer is not None
    assert hit.manufacturer.name == "Acme Pharma"
    assert [i.name for i in hit.ingredients] == ["Ascorbic Acid"]
    assert len(hit.warnings) == 1
    assert "exceed" in hit.warnings[0].text
    assert len(hit.recalls) == 1
    assert hit.recalls[0].classification == "class_ii"
    assert hit.source.source_system == "test"


def test_product_warning_recall_hits_link_to_dailymed_when_spl_set_id_known(
    db_session: Session,
) -> None:
    """A citation is only independently verifiable if a user can actually
    click through to it -- both openFDA and DailyMed ingestion attach a
    Reference(SPL_SET_ID) to every Product (ingestion/openfda/persistence.py,
    ingestion/dailymed/persistence.py), which resolves to a real DailyMed
    label page regardless of which adapter ingested the record."""
    source_id = _make_source(db_session)
    manufacturer = manufacturer_repository(db_session).create(
        name="Acme Pharma", normalized_name="acme pharma", source_id=source_id
    )
    product = product_repository(db_session).create(
        name="Vitamin C Tablets",
        product_type="dietary supplement",
        dosage_form="tablet",
        manufacturer_id=manufacturer.id,
        source_id=source_id,
    )
    db_session.add(
        Reference(
            entity_type=EntityType.PRODUCT,
            entity_id=product.id,
            reference_type=ReferenceType.SPL_SET_ID,
            reference_value="11111111-1111-1111-1111-111111111111",
            source_id=source_id,
        )
    )
    db_session.add(
        Warning(
            product_id=product.id,
            category=WarningCategory.PRECAUTION,
            text="Do not exceed the recommended daily dose",
            status=RecordStatus.ACTIVE,
            version_number=1,
            source_id=source_id,
        )
    )
    db_session.add(
        Recall(
            product_id=product.id,
            manufacturer_id=manufacturer.id,
            reason="Possible contamination found in tablets",
            classification=RecallClassification.CLASS_II,
            status=RecallStatus.ONGOING,
            source_id=source_id,
        )
    )
    db_session.flush()

    expected_url = (
        "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm"
        "?setid=11111111-1111-1111-1111-111111111111"
    )

    product_hits = search_products(db_session, "vitamin c tablets")
    assert product_hits[0].external_url == expected_url

    warning_hits = search_warnings(db_session, "exceed")
    assert warning_hits[0].external_url == expected_url

    recall_hits = search_recalls(db_session, "contamination")
    assert recall_hits[0].external_url == expected_url


def test_product_hit_external_url_is_none_without_a_spl_set_id_reference(
    db_session: Session,
) -> None:
    source_id = _make_source(db_session)
    product_repository(db_session).create(
        name="No Reference Product",
        product_type=None,
        dosage_form=None,
        manufacturer_id=None,
        source_id=source_id,
    )
    db_session.flush()

    hits = search_products(db_session, "no reference product")

    assert hits[0].external_url is None


def test_search_warnings_returns_owning_product(db_session: Session) -> None:
    source_id = _make_source(db_session)
    product = product_repository(db_session).create(
        name="Test Product",
        product_type=None,
        dosage_form=None,
        manufacturer_id=None,
        source_id=source_id,
    )
    db_session.add(
        Warning(
            product_id=product.id,
            category=WarningCategory.BOXED_WARNING,
            text="Serious cardiovascular risk reported",
            status=RecordStatus.ACTIVE,
            version_number=1,
            source_id=source_id,
        )
    )
    db_session.flush()

    hits = search_warnings(db_session, "cardiovascular")

    assert len(hits) == 1
    assert hits[0].product.id == product.id
    assert hits[0].product.name == "Test Product"
    assert hits[0].category == "boxed_warning"


def test_search_recalls_returns_owning_product_and_manufacturer(db_session: Session) -> None:
    source_id = _make_source(db_session)
    manufacturer = manufacturer_repository(db_session).create(
        name="Acme Pharma", normalized_name="acme pharma", source_id=source_id
    )
    product = product_repository(db_session).create(
        name="Test Product",
        product_type=None,
        dosage_form=None,
        manufacturer_id=manufacturer.id,
        source_id=source_id,
    )
    db_session.add(
        Recall(
            product_id=product.id,
            manufacturer_id=manufacturer.id,
            reason="Undeclared allergen present in formulation",
            classification=RecallClassification.CLASS_I,
            status=RecallStatus.ONGOING,
            source_id=source_id,
        )
    )
    db_session.flush()

    hits = search_recalls(db_session, "allergen")

    assert len(hits) == 1
    assert hits[0].product is not None
    assert hits[0].product.id == product.id
    assert hits[0].manufacturer is not None
    assert hits[0].manufacturer.name == "Acme Pharma"
