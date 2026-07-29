from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Computed, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models._types import str_enum
from database.models.base import Base
from database.models.enums import RecallClassification, RecallStatus

if TYPE_CHECKING:
    from database.models.manufacturer import Manufacturer
    from database.models.product import Product
    from database.models.source import Source


class Recall(Base):
    """Regulatory recall action against a product and/or manufacturer."""

    __tablename__ = "recalls"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    manufacturer_id: Mapped[str | None] = mapped_column(
        ForeignKey("manufacturers.id", ondelete="RESTRICT")
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    classification: Mapped[RecallClassification] = mapped_column(
        str_enum(RecallClassification), nullable=False
    )
    status: Mapped[RecallStatus] = mapped_column(
        str_enum(RecallStatus), nullable=False, default=RecallStatus.ONGOING
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False
    )
    initiated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terminated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # DB-generated -- see ingredient.py's IngredientVersion.search_vector comment.
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', reason)", persisted=True)
    )

    product: Mapped["Product | None"] = relationship()
    manufacturer: Mapped["Manufacturer | None"] = relationship()
    source: Mapped["Source"] = relationship()
