from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models._types import str_enum
from database.models.base import Base
from database.models.enums import RecordStatus, WarningCategory

if TYPE_CHECKING:
    from database.models.product import Product
    from database.models.source import Source


class Warning(Base):
    """Safety-relevant statement attached to a product — see CANONICAL_MODEL.md Section 3."""

    __tablename__ = "warnings"
    __table_args__ = (Index("ix_warnings_product_version", "product_id", "version_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[str] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    category: Mapped[WarningCategory] = mapped_column(str_enum(WarningCategory), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[RecordStatus] = mapped_column(
        str_enum(RecordStatus), nullable=False, default=RecordStatus.ACTIVE
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    product: Mapped["Product"] = relationship()
    source: Mapped["Source"] = relationship()
