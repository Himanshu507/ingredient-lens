from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models._types import str_enum
from database.models.base import Base
from database.models.enums import EntityType

if TYPE_CHECKING:
    from database.models.source import Source


class Alias(Base):
    """Alternate name resolving to a canonical ingredient or manufacturer.

    `entity_id` is a polymorphic pointer (per `entity_type`) rather than a
    foreign key, to avoid a combinatorial join table per entity type — see
    DATABASE_DESIGN.md Section 4.
    """

    __tablename__ = "aliases"
    __table_args__ = (
        Index("ix_aliases_entity", "entity_type", "entity_id"),
        Index("ix_aliases_normalized_alias_text", "normalized_alias_text"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[EntityType] = mapped_column(str_enum(EntityType), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(32), nullable=False)
    alias_text: Mapped[str] = mapped_column(String(256), nullable=False)
    normalized_alias_text: Mapped[str] = mapped_column(String(256), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    source: Mapped["Source | None"] = relationship()
