from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models._types import str_enum
from database.models.base import Base
from database.models.enums import EntityType, ReferenceType

if TYPE_CHECKING:
    from database.models.source import Source


class Reference(Base):
    """Typed external identifier attached to a canonical entity (UNII, CAS, NDC, ...).

    `entity_id` is a polymorphic pointer (per `entity_type`), same rationale as `Alias`.
    """

    __tablename__ = "references"
    __table_args__ = (
        Index("ix_references_entity", "entity_type", "entity_id"),
        Index("ix_references_type_value", "reference_type", "reference_value"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[EntityType] = mapped_column(str_enum(EntityType), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(32), nullable=False)
    reference_type: Mapped[ReferenceType] = mapped_column(str_enum(ReferenceType), nullable=False)
    reference_value: Mapped[str] = mapped_column(String(256), nullable=False)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    source: Mapped["Source"] = relationship()
