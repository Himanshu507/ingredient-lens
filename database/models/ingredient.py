from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models._types import str_enum
from database.models.base import Base
from database.models.enums import RecordStatus

if TYPE_CHECKING:
    from database.models.source import Source


class Ingredient(Base):
    """Stable entity identity row — see DATABASE_DESIGN.md Section 2."""

    __tablename__ = "ingredients"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    current_version_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "ingredient_versions.id", use_alter=True, name="fk_ingredients_current_version_id"
        )
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    versions: Mapped[list["IngredientVersion"]] = relationship(
        foreign_keys="IngredientVersion.ingredient_id", back_populates="ingredient"
    )
    current_version: Mapped["IngredientVersion | None"] = relationship(
        foreign_keys=[current_version_id], post_update=True
    )


class IngredientVersion(Base):
    """Immutable version history for ingredients — see DATABASE_DESIGN.md Section 2."""

    __tablename__ = "ingredient_versions"
    __table_args__ = (
        UniqueConstraint(
            "ingredient_id", "version_number", name="uq_ingredient_versions_entity_version"
        ),
        Index("ix_ingredient_versions_entity_version", "ingredient_id", "version_number"),
        Index("ix_ingredient_versions_normalized_name", "normalized_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ingredient_id: Mapped[str] = mapped_column(
        ForeignKey("ingredients.id", ondelete="RESTRICT"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[RecordStatus] = mapped_column(
        str_enum(RecordStatus), nullable=False, default=RecordStatus.ACTIVE
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    ingredient: Mapped["Ingredient"] = relationship(
        foreign_keys=[ingredient_id], back_populates="versions"
    )
    source: Mapped["Source"] = relationship()
