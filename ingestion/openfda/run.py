import itertools
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from database.models.enums import IngestionRunStatus
from database.models.ingestion_log import IngestionLog
from database.models.source import Source
from ingestion.openfda.models import OpenFdaDrugLabelRecord
from ingestion.openfda.persistence import save_drug_label_candidate
from ingestion.openfda.transformer import transform_drug_label_record
from ingestion.openfda.validator import validate_drug_label_record

# How many records between checkpoint writes. Bounds how much work a resume
# re-does after a mid-run failure (INGESTION_STRATEGY.md Section 5) without
# flushing the checkpoint on every single record.
DEFAULT_CHECKPOINT_BATCH_SIZE = 50

_RESUMABLE_STATUSES = (IngestionRunStatus.RUNNING, IngestionRunStatus.PARTIAL)


def find_resumable_run(session: Session, *, source: str, endpoint: str) -> IngestionLog | None:
    """Find an incomplete prior run for this source/endpoint to resume, if any.

    Per INGESTION_STRATEGY.md Section 5: "on restart, an adapter first checks
    for an incomplete run for its source." Most recent incomplete run wins if
    there happens to be more than one.
    """
    candidates = (
        session.execute(
            sa.select(IngestionLog)
            .where(
                IngestionLog.source == source,
                IngestionLog.status.in_(_RESUMABLE_STATUSES),
            )
            .order_by(IngestionLog.started_at.desc())
        )
        .scalars()
        .all()
    )
    for log in candidates:
        checkpoint = log.checkpoint_state or {}
        if checkpoint.get("endpoint") == endpoint:
            return log
    return None


def _checkpoint(
    log: IngestionLog, *, endpoint: str, records_processed: int, counts: dict[str, int]
) -> None:
    log.checkpoint_state = {"endpoint": endpoint, "records_processed": records_processed}
    log.records_fetched = counts["fetched"]
    log.records_validated = counts["validated"]
    log.records_created = counts["created"]
    log.records_updated = counts["updated"]
    log.records_unchanged = counts["unchanged"]
    log.records_rejected = counts["rejected"]


def ingest_drug_label_records(
    session: Session,
    records: Iterable[OpenFdaDrugLabelRecord],
    *,
    endpoint: str = "drug/label",
    run_id: str | None = None,
    checkpoint_batch_size: int = DEFAULT_CHECKPOINT_BATCH_SIZE,
) -> IngestionLog:
    """Run validate() -> transform() -> save() over a stream of parsed records.

    Writes one `Source` row and one `ingestion_logs` entry per run
    (INGESTION_STRATEGY.md Section 9) — not stopping on a single bad record
    (Section 7: a malformed record is logged and skipped, not fatal).
    `records` can come from either the API adapter or the bulk adapter
    (Brick 5); this stage doesn't know or care which.

    Resumable: if an incomplete (`running`/`partial`) prior run exists for
    this source/endpoint, it's resumed instead of starting a new one —
    `records` must be the *full*, un-truncated stream each time; the already-
    processed prefix is skipped here via the checkpoint, per Section 5. A
    smarter caller could instead re-fetch starting past the checkpoint
    (avoiding re-fetching already-processed pages over the network) — not
    done here; that's a real optimization opportunity, not implemented since
    correctness, not fetch efficiency, is this brick's concern.
    """
    resumed = None if run_id else find_resumable_run(session, source="openfda", endpoint=endpoint)

    counts: dict[str, int]
    if resumed is not None:
        log = resumed
        run_id = log.run_id
        checkpoint = log.checkpoint_state or {}
        already_processed = checkpoint.get("records_processed", 0)
        source_row = session.execute(
            sa.select(Source).where(Source.ingestion_run_id == run_id)
        ).scalar_one()
        counts = {
            "fetched": log.records_fetched,
            "validated": log.records_validated,
            "created": log.records_created,
            "updated": log.records_updated,
            "unchanged": log.records_unchanged,
            "rejected": log.records_rejected,
        }
        log.status = IngestionRunStatus.RUNNING
        records_iter: Iterable[OpenFdaDrugLabelRecord] = itertools.islice(
            records, already_processed, None
        )
    else:
        run_id = run_id or str(uuid.uuid4())
        started_at = datetime.now(UTC)

        source_row = Source(
            source_system="openfda",
            endpoint_or_document_type=endpoint,
            ingestion_run_id=run_id,
            ingested_at=started_at,
        )
        session.add(source_row)
        session.flush()

        log = IngestionLog(
            source="openfda",
            run_id=run_id,
            status=IngestionRunStatus.RUNNING,
            checkpoint_state={"endpoint": endpoint, "records_processed": 0},
            started_at=started_at,
        )
        session.add(log)
        session.flush()

        already_processed = 0
        counts = dict.fromkeys(
            ("fetched", "validated", "created", "updated", "unchanged", "rejected"), 0
        )
        records_iter = records

    processed_this_attempt = 0
    try:
        for record in records_iter:
            counts["fetched"] += 1
            processed_this_attempt += 1

            rejection_reasons = validate_drug_label_record(record)
            if rejection_reasons:
                counts["rejected"] += 1
            else:
                counts["validated"] += 1
                candidate = transform_drug_label_record(record)
                result = save_drug_label_candidate(session, candidate, source_id=source_row.id)
                counts[result.outcome] += 1

            if processed_this_attempt % checkpoint_batch_size == 0:
                _checkpoint(
                    log,
                    endpoint=endpoint,
                    records_processed=already_processed + processed_this_attempt,
                    counts=counts,
                )
                session.flush()
    except Exception:
        log.status = IngestionRunStatus.PARTIAL
        session.flush()
        raise

    _checkpoint(
        log,
        endpoint=endpoint,
        records_processed=already_processed + processed_this_attempt,
        counts=counts,
    )
    log.status = IngestionRunStatus.COMPLETED
    log.completed_at = datetime.now(UTC)
    session.flush()

    return log
