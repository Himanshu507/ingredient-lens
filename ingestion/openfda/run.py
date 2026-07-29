import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from database.models.enums import IngestionRunStatus
from database.models.ingestion_log import IngestionLog
from database.models.source import Source
from ingestion.openfda.models import OpenFdaDrugLabelRecord
from ingestion.openfda.persistence import save_drug_label_candidate
from ingestion.openfda.transformer import transform_drug_label_record
from ingestion.openfda.validator import validate_drug_label_record


def ingest_drug_label_records(
    session: Session,
    records: Iterable[OpenFdaDrugLabelRecord],
    *,
    endpoint: str = "drug/label",
    run_id: str | None = None,
) -> IngestionLog:
    """Run validate() -> transform() -> save() over a stream of parsed records.

    Writes one `Source` row and one `ingestion_logs` entry per run
    (INGESTION_STRATEGY.md Section 9) — not stopping on a single bad record
    (Section 7: a malformed record is logged and skipped, not fatal).
    `records` can come from either the API adapter or the bulk adapter
    (Brick 5); this stage doesn't know or care which.
    """
    run_id = run_id or str(uuid.uuid4())
    started_at = datetime.now(UTC)

    source = Source(
        source_system="openfda",
        endpoint_or_document_type=endpoint,
        ingestion_run_id=run_id,
        ingested_at=started_at,
    )
    session.add(source)
    session.flush()

    log = IngestionLog(
        source="openfda",
        run_id=run_id,
        status=IngestionRunStatus.RUNNING,
        started_at=started_at,
    )
    session.add(log)
    session.flush()

    records_fetched = 0
    records_validated = 0
    records_created = 0
    records_updated = 0
    records_unchanged = 0
    records_rejected = 0

    for record in records:
        records_fetched += 1

        rejection_reasons = validate_drug_label_record(record)
        if rejection_reasons:
            records_rejected += 1
            continue
        records_validated += 1

        candidate = transform_drug_label_record(record)
        result = save_drug_label_candidate(session, candidate, source_id=source.id)

        if result.outcome == "created":
            records_created += 1
        elif result.outcome == "updated":
            records_updated += 1
        else:
            records_unchanged += 1

    log.records_fetched = records_fetched
    log.records_validated = records_validated
    log.records_created = records_created
    log.records_updated = records_updated
    log.records_unchanged = records_unchanged
    log.records_rejected = records_rejected
    log.status = IngestionRunStatus.COMPLETED
    log.completed_at = datetime.now(UTC)
    session.flush()

    return log
