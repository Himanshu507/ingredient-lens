"""Dead letter queue (ERROR_HANDLING.md Section 3).

A rejected record — validation failure, transform failure, or a save-level
failure — is written here rather than silently dropped or allowed to halt
the run. Dead-lettered records are reviewable and, once the underlying
cause is fixed, re-processable through the exact same pipeline stages as
live ingestion (not a special-cased recovery path), so they benefit from
the same idempotency guarantees as any other input.
"""

from typing import Any

from sqlalchemy.orm import Session

from database.models.dead_letter import IngestionDeadLetter
from database.models.enums import DeadLetterStage


def write_dead_letter(
    session: Session,
    *,
    source: str,
    run_id: str,
    stage: DeadLetterStage,
    record_identifier: str | None,
    raw_payload: dict[str, Any],
    error: str,
) -> IngestionDeadLetter:
    dead_letter = IngestionDeadLetter(
        source=source,
        run_id=run_id,
        stage=stage,
        record_identifier=record_identifier,
        raw_payload=raw_payload,
        error_message=error,
    )
    session.add(dead_letter)
    session.flush()
    return dead_letter
