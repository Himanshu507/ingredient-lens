from datetime import datetime

from sqlalchemy import DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database.models._types import str_enum
from database.models.base import Base
from database.models.enums import EntityType, ReviewStatus


class EntityResolutionReview(Base):
    """Queue of low-confidence match candidates awaiting manual review.

    See ENTITY_RESOLUTION.md Sections 6-7.
    """

    __tablename__ = "entity_resolution_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[EntityType] = mapped_column(str_enum(EntityType), nullable=False)
    candidate_a_id: Mapped[str] = mapped_column(String(32), nullable=False)
    candidate_b_id: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence_score: Mapped[float] = mapped_column(Numeric, nullable=False)
    status: Mapped[ReviewStatus] = mapped_column(
        str_enum(ReviewStatus), nullable=False, default=ReviewStatus.PENDING
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(128))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
