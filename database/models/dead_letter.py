from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database.models._types import str_enum
from database.models.base import Base
from database.models.enums import DeadLetterStage


class IngestionDeadLetter(Base):
    """A record- or batch-level ingestion failure — ERROR_HANDLING.md Section 3.

    Reviewable and re-processable once the underlying cause is fixed: a
    dead-lettered record goes back through the exact same pipeline stages as
    live ingestion (no special-cased recovery path), so it benefits from the
    same idempotency guarantees as any other input.
    """

    __tablename__ = "ingestion_dead_letters"
    __table_args__ = (Index("ix_ingestion_dead_letters_source_stage", "source", "stage"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    stage: Mapped[DeadLetterStage] = mapped_column(str_enum(DeadLetterStage), nullable=False)
    record_identifier: Mapped[str | None] = mapped_column(String(256))
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    reprocessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
