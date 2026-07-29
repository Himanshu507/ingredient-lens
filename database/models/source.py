from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base


class Source(Base):
    """Provenance record for every ingested fact — see CANONICAL_MODEL.md Section 7."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_system: Mapped[str] = mapped_column(String(64), nullable=False)
    endpoint_or_document_type: Mapped[str] = mapped_column(String(128), nullable=False)
    ingestion_run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_payload_ref: Mapped[str | None] = mapped_column(String(512))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
