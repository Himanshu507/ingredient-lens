from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database.models._types import str_enum
from database.models.base import Base
from database.models.enums import IngestionRunStatus


class IngestionLog(Base):
    """Per-run ingestion outcome, checkpointing, and audit trail.

    See INGESTION_STRATEGY.md Section 9.
    """

    __tablename__ = "ingestion_logs"
    __table_args__ = (
        Index("ix_ingestion_logs_source_status_started", "source", "status", "started_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[IngestionRunStatus] = mapped_column(str_enum(IngestionRunStatus), nullable=False)
    checkpoint_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    records_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_validated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
