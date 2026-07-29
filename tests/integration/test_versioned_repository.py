from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from database.access.ingredients import ingredient_repository
from database.access.manufacturers import manufacturer_repository
from database.access.products import product_repository
from database.models.enums import RecordStatus
from database.models.source import Source


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


def test_create_writes_identity_and_first_version(db_session: Session) -> None:
    source_id = _make_source(db_session)
    repo = ingredient_repository(db_session)

    ingredient = repo.create(
        name="Ascorbic Acid",
        normalized_name="ascorbic acid",
        source_id=source_id,
    )

    assert ingredient.id.startswith("ING-")
    assert ingredient.current_version is not None
    assert ingredient.current_version.version_number == 1
    assert ingredient.current_version.name == "Ascorbic Acid"
    assert ingredient.current_version.status == RecordStatus.ACTIVE


def test_add_version_increments_and_repoints_current(db_session: Session) -> None:
    source_id = _make_source(db_session)
    repo = ingredient_repository(db_session)
    ingredient = repo.create(
        name="Ascorbic Acid", normalized_name="ascorbic acid", source_id=source_id
    )

    repo.add_version(
        ingredient.id,
        name="Ascorbic Acid (corrected)",
        normalized_name="ascorbic acid",
        source_id=source_id,
    )
    db_session.flush()
    db_session.refresh(ingredient)

    assert ingredient.current_version is not None
    assert ingredient.current_version.version_number == 2
    assert ingredient.current_version.name == "Ascorbic Acid (corrected)"

    history = repo.get_history(ingredient.id)
    assert [v.version_number for v in history] == [1, 2]
    assert history[0].name == "Ascorbic Acid"


def test_retraction_is_a_new_version_not_a_delete(db_session: Session) -> None:
    """Soft delete per DATABASE_DESIGN.md Section 3: a status-changing version,
    never a row deletion — the prior version stays in `get_history`."""
    source_id = _make_source(db_session)
    repo = ingredient_repository(db_session)
    ingredient = repo.create(
        name="Contaminated Batch X", normalized_name="contaminated batch x", source_id=source_id
    )

    repo.add_version(
        ingredient.id,
        name="Contaminated Batch X",
        normalized_name="contaminated batch x",
        status=RecordStatus.RETRACTED,
        source_id=source_id,
    )
    db_session.refresh(ingredient)

    assert ingredient.current_version is not None
    assert ingredient.current_version.status == RecordStatus.RETRACTED
    assert len(repo.get_history(ingredient.id)) == 2


def test_get_current_returns_none_for_unknown_id(db_session: Session) -> None:
    repo = ingredient_repository(db_session)
    assert repo.get_current("ING-999999") is None


def test_add_version_raises_for_unknown_entity(db_session: Session) -> None:
    source_id = _make_source(db_session)
    repo = ingredient_repository(db_session)

    with pytest.raises(ValueError, match="does not exist"):
        repo.add_version("ING-999999", name="Ghost", normalized_name="ghost", source_id=source_id)


def test_manufacturer_repository_lifecycle(db_session: Session) -> None:
    source_id = _make_source(db_session)
    repo = manufacturer_repository(db_session)

    manufacturer = repo.create(
        name="Acme Pharma", normalized_name="acme pharma", source_id=source_id
    )
    assert manufacturer.id.startswith("MFR-")
    assert manufacturer.current_version is not None
    assert manufacturer.current_version.version_number == 1

    repo.add_version(
        manufacturer.id,
        name="Acme Pharma Inc.",
        normalized_name="acme pharma inc",
        source_id=source_id,
    )
    db_session.refresh(manufacturer)
    assert manufacturer.current_version is not None
    assert manufacturer.current_version.version_number == 2


def test_product_repository_lifecycle(db_session: Session) -> None:
    source_id = _make_source(db_session)
    manufacturer = manufacturer_repository(db_session).create(
        name="Acme Pharma", normalized_name="acme pharma", source_id=source_id
    )
    repo = product_repository(db_session)

    product = repo.create(
        name="Acme Vitamin C 500mg",
        product_type="dietary supplement",
        dosage_form="tablet",
        manufacturer_id=manufacturer.id,
        source_id=source_id,
    )

    assert product.id.startswith("PRD-")
    assert product.current_version is not None
    assert product.current_version.dosage_form == "tablet"
    assert product.current_version.manufacturer_id == manufacturer.id
