from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models._types import str_enum
from database.models.base import Base
from database.models.enums import RecordStatus

if TYPE_CHECKING:
    from database.models.source import Source


class Manufacturer(Base):
    """Stable entity identity row — mirrors the `Ingredient` identity/version pattern."""

    __tablename__ = "manufacturers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    current_version_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "manufacturer_versions.id", use_alter=True, name="fk_manufacturers_current_version_id"
        )
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    versions: Mapped[list["ManufacturerVersion"]] = relationship(
        foreign_keys="ManufacturerVersion.manufacturer_id", back_populates="manufacturer"
    )
    current_version: Mapped["ManufacturerVersion | None"] = relationship(
        foreign_keys=[current_version_id], post_update=True
    )


class ManufacturerVersion(Base):
    """Immutable version history for manufacturers."""

    __tablename__ = "manufacturer_versions"
    __table_args__ = (
        UniqueConstraint(
            "manufacturer_id", "version_number", name="uq_manufacturer_versions_entity_version"
        ),
        Index("ix_manufacturer_versions_entity_version", "manufacturer_id", "version_number"),
        Index("ix_manufacturer_versions_normalized_name", "normalized_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    manufacturer_id: Mapped[str] = mapped_column(
        ForeignKey("manufacturers.id", ondelete="RESTRICT"), nullable=False
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

    manufacturer: Mapped["Manufacturer"] = relationship(
        foreign_keys=[manufacturer_id], back_populates="versions"
    )
    source: Mapped["Source"] = relationship()
