import base64
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from database.models.dead_letter import IngestionDeadLetter
from database.models.enums import DeadLetterStage, IngestionRunStatus
from database.models.product import Product
from ingestion.dailymed.extraction import SplPackage
from ingestion.dailymed.run import ingest_spl_documents, reprocess_dead_letters
from ingestion.openfda.parser import parse_drug_label_record
from ingestion.openfda.run import ingest_drug_label_records
from ingestion.openfda.run import reprocess_dead_letters as reprocess_openfda_dead_letters

OPENFDA_GOLDEN = Path(__file__).parent.parent / "golden" / "openfda"
DAILYMED_GOLDEN = Path(__file__).parent.parent / "golden" / "dailymed"


def _openfda_records() -> list[Any]:
    records = []
    for name in ["drug_label_otc.json", "drug_label_boxed_warning.json"]:
        with (OPENFDA_GOLDEN / name).open() as f:
            raw = json.load(f)
        records.append(parse_drug_label_record(raw))
    return records


def _count(session: Session, model: type) -> int:
    return session.execute(sa.select(sa.func.count()).select_from(model)).scalar_one()


def test_validation_failure_is_dead_lettered_and_run_continues(db_session: Session) -> None:
    otc, boxed = _openfda_records()
    unusable = replace(otc, set_id="dlq-validation-test", brand_name=None, generic_name=None)

    log = ingest_drug_label_records(db_session, [unusable, boxed])

    assert log.status == IngestionRunStatus.COMPLETED
    assert log.records_fetched == 2
    assert log.records_rejected == 1
    assert log.records_created == 1  # `boxed` still made it through

    dead_letter = db_session.execute(
        sa.select(IngestionDeadLetter).where(
            IngestionDeadLetter.record_identifier == "dlq-validation-test"
        )
    ).scalar_one()
    assert dead_letter.stage == DeadLetterStage.VALIDATION
    assert dead_letter.source == "openfda"
    assert "product name" in dead_letter.error_message
    # raw_payload is the record's original archived JSON (record.raw) --
    # `record_identifier` is what carries the *parsed* set_id used to build
    # this test case; the two aren't expected to match here.
    assert "openfda" in dead_letter.raw_payload


def test_save_stage_failure_is_dead_lettered_and_run_continues(db_session: Session) -> None:
    """A real, injectable batch/save-level failure: a manufacturer name that
    exceeds the column's length constraint raises during save, not
    validation -- ERROR_HANDLING.md Section 1's "database constraint
    violation" category. One bad record must not lose the others in the
    same run (that's the whole point of the savepoint)."""
    otc, boxed = _openfda_records()
    too_long = replace(otc, set_id="dlq-save-test", manufacturer_name="X" * 500)

    log = ingest_drug_label_records(db_session, [too_long, boxed])

    assert log.status == IngestionRunStatus.COMPLETED  # not partial!
    assert log.records_rejected == 1
    assert log.records_created == 1

    dead_letter = db_session.execute(
        sa.select(IngestionDeadLetter).where(
            IngestionDeadLetter.record_identifier == "dlq-save-test"
        )
    ).scalar_one()
    assert dead_letter.stage == DeadLetterStage.SAVE
    assert dead_letter.source == "openfda"

    # The failed record's manufacturer was never left half-created.
    assert _count(db_session, Product) == 1


def test_reprocessing_a_fixed_dead_letter_succeeds(db_session: Session) -> None:
    otc, boxed = _openfda_records()
    unusable = replace(otc, set_id="dlq-reprocess-test", brand_name=None, generic_name=None)

    ingest_drug_label_records(db_session, [unusable, boxed])
    dead_letter = db_session.execute(
        sa.select(IngestionDeadLetter).where(
            IngestionDeadLetter.record_identifier == "dlq-reprocess-test"
        )
    ).scalar_one()
    assert dead_letter.reprocessed_at is None

    # Simulate the underlying cause being fixed: the archived raw payload is
    # corrected (e.g. upstream backfilled the missing field).
    dead_letter.raw_payload = {
        **dead_letter.raw_payload,
        "openfda": {
            **dead_letter.raw_payload.get("openfda", {}),
            "brand_name": ["Fixed Product Name"],
        },
    }
    db_session.flush()

    reprocess_log = reprocess_openfda_dead_letters(db_session, [dead_letter])

    assert reprocess_log.records_created == 1
    assert dead_letter.reprocessed_at is not None

    reference_count = db_session.execute(
        sa.select(sa.func.count()).select_from(Product)
    ).scalar_one()
    assert reference_count == 2  # `boxed` (from setup) + the reprocessed one


def test_dailymed_validation_failure_is_dead_lettered_and_run_continues(
    db_session: Session,
) -> None:
    valid = SplPackage(
        package_name="human_rx_injection.xml",
        xml_bytes=(DAILYMED_GOLDEN / "human_rx_injection.xml").read_bytes(),
    )
    broken = SplPackage(
        package_name="no_ingredients_section.xml",
        xml_bytes=(DAILYMED_GOLDEN / "no_ingredients_section.xml").read_bytes(),
    )

    log = ingest_spl_documents(db_session, [broken, valid])

    assert log.status == IngestionRunStatus.COMPLETED
    assert log.records_rejected == 1
    assert log.records_created == 1

    dead_letter = db_session.execute(
        sa.select(IngestionDeadLetter).where(IngestionDeadLetter.source == "dailymed")
    ).scalar_one()
    assert dead_letter.stage == DeadLetterStage.VALIDATION
    assert dead_letter.record_identifier == "11111111-1111-1111-1111-111111111111"


def test_dailymed_save_stage_failure_is_dead_lettered_and_run_continues(
    db_session: Session,
) -> None:
    valid_xml = (DAILYMED_GOLDEN / "otc_liquid_bandage.xml").read_bytes()
    too_long_xml = valid_xml.replace(b"Meijer Distribution Inc", b"M" * 500)

    valid = SplPackage(package_name="valid.zip", xml_bytes=valid_xml)
    broken = SplPackage(package_name="too_long.zip", xml_bytes=too_long_xml)

    log = ingest_spl_documents(db_session, [broken, valid])

    assert log.status == IngestionRunStatus.COMPLETED
    assert log.records_rejected == 1
    assert log.records_created == 1

    dead_letter = db_session.execute(
        sa.select(IngestionDeadLetter).where(IngestionDeadLetter.source == "dailymed")
    ).scalar_one()
    assert dead_letter.stage == DeadLetterStage.SAVE

    # Reprocessing works from the base64-encoded raw payload too -- the "fix"
    # is restoring the real manufacturer name. Its set_id is identical to
    # `valid`'s (same source document, just repaired), so reprocessing
    # correctly recognizes it as the *same* already-ingested product
    # (idempotency), not a duplicate creation.
    dead_letter.raw_payload = {
        "package_name": dead_letter.raw_payload["package_name"],
        "xml_base64": base64.b64encode(valid_xml).decode("ascii"),
    }
    db_session.flush()

    reprocess_log = reprocess_dead_letters(db_session, [dead_letter])
    assert reprocess_log.records_unchanged == 1
    assert dead_letter.reprocessed_at is not None
