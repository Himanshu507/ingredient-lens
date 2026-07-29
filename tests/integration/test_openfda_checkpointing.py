import json
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from database.models.enums import IngestionRunStatus
from database.models.ingestion_log import IngestionLog
from database.models.product import Product
from ingestion.openfda.models import OpenFdaDrugLabelRecord
from ingestion.openfda.parser import parse_drug_label_record
from ingestion.openfda.run import find_resumable_run, ingest_drug_label_records

GOLDEN_DIR = Path(__file__).parent.parent / "golden" / "openfda"


def _load(name: str) -> dict[str, Any]:
    with (GOLDEN_DIR / name).open() as f:
        result: dict[str, Any] = json.load(f)
        return result


def _five_distinct_records() -> list[OpenFdaDrugLabelRecord]:
    otc = parse_drug_label_record(_load("drug_label_otc.json"))
    boxed = parse_drug_label_record(_load("drug_label_boxed_warning.json"))
    # Three more distinct, valid records derived from the real otc fixture.
    extra = [
        replace(otc, set_id=f"synthetic-{i}", brand_name=f"Synthetic Product {i}") for i in range(3)
    ]
    return [otc, boxed, *extra]


class _CrashAfterN:
    """Wraps a record list, raising partway through — simulates a mid-run crash."""

    def __init__(self, records: list[OpenFdaDrugLabelRecord], crash_after: int) -> None:
        self._records = records
        self._crash_after = crash_after

    def __iter__(self) -> Iterator[OpenFdaDrugLabelRecord]:
        for i, record in enumerate(self._records):
            if i == self._crash_after:
                raise RuntimeError("simulated mid-run crash")
            yield record


def _count(session: Session, model: type) -> int:
    return session.execute(sa.select(sa.func.count()).select_from(model)).scalar_one()


def test_mid_run_failure_leaves_a_resumable_partial_log(db_session: Session) -> None:
    records = _five_distinct_records()

    with pytest.raises(RuntimeError, match="simulated mid-run crash"):
        ingest_drug_label_records(
            db_session, _CrashAfterN(records, crash_after=3), checkpoint_batch_size=1
        )

    resumable = find_resumable_run(db_session, source="openfda", endpoint="drug/label")
    assert resumable is not None
    assert resumable.status == IngestionRunStatus.PARTIAL
    assert resumable.checkpoint_state is not None
    assert resumable.checkpoint_state["records_processed"] == 3
    assert resumable.records_created == 3
    assert _count(db_session, Product) == 3


def test_resume_completes_without_reprocessing_or_duplicating(db_session: Session) -> None:
    records = _five_distinct_records()

    with pytest.raises(RuntimeError):
        ingest_drug_label_records(
            db_session, _CrashAfterN(records, crash_after=3), checkpoint_batch_size=1
        )

    # "Restart": same source/endpoint, full original record list passed again —
    # the already-processed prefix must be skipped via the checkpoint, not redone.
    log = ingest_drug_label_records(db_session, records, checkpoint_batch_size=1)

    assert log.status == IngestionRunStatus.COMPLETED
    assert log.records_fetched == 5
    assert log.records_created == 5
    assert log.records_rejected == 0
    assert log.checkpoint_state is not None
    assert log.checkpoint_state["records_processed"] == 5

    # No duplicates: exactly 5 products, not 8 (3 from before the crash + 5 redone).
    assert _count(db_session, Product) == 5

    # Only one ingestion_logs row for this run -- resume updated it in place,
    # it didn't create a second one.
    logs_for_run = db_session.execute(
        sa.select(sa.func.count())
        .select_from(IngestionLog)
        .where(IngestionLog.run_id == log.run_id)
    ).scalar_one()
    assert logs_for_run == 1


def test_no_resumable_run_found_when_none_incomplete(db_session: Session) -> None:
    assert find_resumable_run(db_session, source="openfda", endpoint="drug/label") is None

    records = _five_distinct_records()
    log = ingest_drug_label_records(db_session, records)
    assert log.status == IngestionRunStatus.COMPLETED

    # Completed runs are not resumable candidates.
    assert find_resumable_run(db_session, source="openfda", endpoint="drug/label") is None
