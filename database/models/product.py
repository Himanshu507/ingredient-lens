from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models._types import str_enum
from database.models.base import Base
from database.models.enums import ProductIngredientRole, RecordStatus

if TYPE_CHECKING:
    from database.models.ingredient import Ingredient
    from database.models.manufacturer import Manufacturer
    from database.models.source import Source


class Product(Base):
    """Stable entity identity row — see DATABASE_DESIGN.md Section 2."""

    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    current_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_versions.id", use_alter=True, name="fk_products_current_version_id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    versions: Mapped[list["ProductVersion"]] = relationship(
        foreign_keys="ProductVersion.product_id", back_populates="product"
    )
    current_version: Mapped["ProductVersion | None"] = relationship(
        foreign_keys=[current_version_id], post_update=True
    )


class ProductVersion(Base):
    """Immutable version history for products — see DATABASE_DESIGN.md Section 2."""

    __tablename__ = "product_versions"
    __table_args__ = (
        UniqueConstraint("product_id", "version_number", name="uq_product_versions_entity_version"),
        Index("ix_product_versions_entity_version", "product_id", "version_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[str] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    product_type: Mapped[str | None] = mapped_column(String(128))
    dosage_form: Mapped[str | None] = mapped_column(String(128))
    manufacturer_id: Mapped[str | None] = mapped_column(
        ForeignKey("manufacturers.id", ondelete="RESTRICT")
    )
    status: Mapped[RecordStatus] = mapped_column(
        str_enum(RecordStatus), nullable=False, default=RecordStatus.ACTIVE
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # DB-generated -- see ingredient.py's IngredientVersion.search_vector comment.
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', name)", persisted=True)
    )

    product: Mapped["Product"] = relationship(foreign_keys=[product_id], back_populates="versions")
    manufacturer: Mapped["Manufacturer | None"] = relationship()
    source: Mapped["Source"] = relationship()
    ingredients: Mapped[list["ProductIngredient"]] = relationship(back_populates="product_version")


class ProductIngredient(Base):
    """Join entity: product version ↔ ingredient, carrying relationship attributes.

    Points at the ingredient's stable identity (not a specific version) — the
    ingredient's own current facts are reached by following that identity's
    `current_version`, per DATABASE_DESIGN.md Section 4.
    """

    __tablename__ = "product_ingredients"

    product_version_id: Mapped[int] = mapped_column(
        ForeignKey("product_versions.id", ondelete="RESTRICT"), primary_key=True
    )
    ingredient_id: Mapped[str] = mapped_column(
        ForeignKey("ingredients.id", ondelete="RESTRICT"), primary_key=True
    )
    role: Mapped[ProductIngredientRole] = mapped_column(
        str_enum(ProductIngredientRole), nullable=False
    )
    quantity: Mapped[float | None] = mapped_column(Numeric)
    unit: Mapped[str | None] = mapped_column(String(32))

    product_version: Mapped["ProductVersion"] = relationship(back_populates="ingredients")
    ingredient: Mapped["Ingredient"] = relationship()
