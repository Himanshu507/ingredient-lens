import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from database.models.enums import IngestionRunStatus
from database.models.ingestion_log import IngestionLog
from database.models.source import Source
from ingestion.dailymed.document_metadata import DocumentMetadataError, extract_document_metadata
from ingestion.dailymed.dosage_extractor import DosageExtractor
from ingestion.dailymed.extraction import SplPackage
from ingestion.dailymed.ingredient_extractor import IngredientExtractor
from ingestion.dailymed.manufacturer_extractor import ManufacturerExtractor
from ingestion.dailymed.persistence import save_spl_document_candidate
from ingestion.dailymed.transformer import transform_spl_document
from ingestion.dailymed.validator import validate_spl_document
from ingestion.dailymed.warning_extractor import WarningExtractor

# How many packages between checkpoint writes.
DEFAULT_CHECKPOINT_BATCH_SIZE = 10

_RESUMABLE_STATUSES = (IngestionRunStatus.RUNNING, IngestionRunStatus.PARTIAL)

_ingredient_extractor = IngredientExtractor()
_manufacturer_extractor = ManufacturerExtractor()
_dosage_extractor = DosageExtractor()
_warning_extractor = WarningExtractor()


def find_resumable_run(session: Session, *, source: str, endpoint: str) -> IngestionLog | None:
    """Same contract as `ingestion.openfda.run.find_resumable_run`, duplicated
    rather than shared: the two adapters' checkpoint *content* differs enough
    (a record count vs. a set of completed package identifiers) that sharing
    just this lookup would buy little — see DAILYMED_INGESTION.md Section 8.
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
    log: IngestionLog, *, endpoint: str, completed_packages: set[str], counts: dict[str, int]
) -> None:
    log.checkpoint_state = {
        "endpoint": endpoint,
        "completed_packages": sorted(completed_packages),
    }
    log.records_fetched = counts["fetched"]
    log.records_validated = counts["validated"]
    log.records_created = counts["created"]
    log.records_updated = counts["updated"]
    log.records_unchanged = counts["unchanged"]
    log.records_rejected = counts["rejected"]


def ingest_spl_documents(
    session: Session,
    packages: Iterable[SplPackage],
    *,
    endpoint: str = "spl",
    run_id: str | None = None,
    checkpoint_batch_size: int = DEFAULT_CHECKPOINT_BATCH_SIZE,
) -> IngestionLog:
    """Run extract -> validate -> transform -> save over a stream of SPL packages.

    Checkpoint granularity is the *package*, not a record count
    (DAILYMED_INGESTION.md Section 8): the checkpoint records which package
    identifiers (nested-ZIP names) are already complete. On resume, any
    package already marked complete is skipped without re-extracting or
    re-parsing it — `packages` must be the full, un-truncated stream each
    time, same contract as `ingestion.openfda.run.ingest_drug_label_records`.
    """
    resumed = None if run_id else find_resumable_run(session, source="dailymed", endpoint=endpoint)

    counts: dict[str, int]
    if resumed is not None:
        log = resumed
        run_id = log.run_id
        checkpoint = log.checkpoint_state or {}
        completed_packages: set[str] = set(checkpoint.get("completed_packages", []))
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
    else:
        run_id = run_id or str(uuid.uuid4())
        started_at = datetime.now(UTC)

        source_row = Source(
            source_system="dailymed",
            endpoint_or_document_type=endpoint,
            ingestion_run_id=run_id,
            ingested_at=started_at,
        )
        session.add(source_row)
        session.flush()

        log = IngestionLog(
            source="dailymed",
            run_id=run_id,
            status=IngestionRunStatus.RUNNING,
            checkpoint_state={"endpoint": endpoint, "completed_packages": []},
            started_at=started_at,
        )
        session.add(log)
        session.flush()

        completed_packages = set()
        counts = dict.fromkeys(
            ("fetched", "validated", "created", "updated", "unchanged", "rejected"), 0
        )

    processed_since_checkpoint = 0
    try:
        for package in packages:
            if package.package_name in completed_packages:
                continue

            counts["fetched"] += 1

            try:
                metadata = extract_document_metadata(package.xml_bytes)
            except DocumentMetadataError:
                counts["rejected"] += 1
                completed_packages.add(package.package_name)
                processed_since_checkpoint += 1
                continue

            ingredients = _ingredient_extractor.extract(package.xml_bytes)
            manufacturer = _manufacturer_extractor.extract(package.xml_bytes)
            dosage = _dosage_extractor.extract(package.xml_bytes)
            warnings = _warning_extractor.extract(package.xml_bytes)

            rejection_reasons = validate_spl_document(metadata, ingredients, manufacturer)
            if rejection_reasons:
                counts["rejected"] += 1
            else:
                counts["validated"] += 1
                assert manufacturer is not None
                candidate = transform_spl_document(
                    metadata, ingredients, manufacturer, dosage, warnings
                )
                result = save_spl_document_candidate(session, candidate, source_id=source_row.id)
                counts[result.outcome] += 1

            completed_packages.add(package.package_name)
            processed_since_checkpoint += 1

            if processed_since_checkpoint % checkpoint_batch_size == 0:
                _checkpoint(
                    log, endpoint=endpoint, completed_packages=completed_packages, counts=counts
                )
                session.flush()
    except Exception:
        log.status = IngestionRunStatus.PARTIAL
        session.flush()
        raise

    _checkpoint(log, endpoint=endpoint, completed_packages=completed_packages, counts=counts)
    log.status = IngestionRunStatus.COMPLETED
    log.completed_at = datetime.now(UTC)
    session.flush()

    return log
