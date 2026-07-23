"""ORM schema: ingredients, their regulatory status, and the LLM staging/cache table.

Table shapes and rationale are documented in README.md Section 3-4 — this module
is just the SQLAlchemy expression of that schema, not a place to redesign it.
"""
from __future__ import annotations

import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Ingredient(Base):
    __tablename__ = "ingredients"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    synonyms: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    statuses: Mapped[list[IngredientRegulatoryStatus]] = relationship(back_populates="ingredient")


class IngredientRegulatoryStatus(Base):
    __tablename__ = "ingredient_regulatory_status"

    id: Mapped[int] = mapped_column(primary_key=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), index=True)
    country_id: Mapped[str] = mapped_column(String(2), default="US")
    normalized_status: Mapped[str] = mapped_column(String(64))
    category_codes: Mapped[list[int]] = mapped_column(ARRAY(Integer))
    reasoning: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    citation_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    citation_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    date_added: Mapped[str | None] = mapped_column(String(7), nullable=True)
    source_staging_id: Mapped[int | None] = mapped_column(
        ForeignKey("extraction_staging.id"), nullable=True
    )

    ingredient: Mapped[Ingredient] = relationship(back_populates="statuses")


class ExtractionStaging(Base):
    """Pre-promotion LLM output: audit log AND Stage 3's idempotency cache.

    Looked up by (ingredient_name, input_hash) before calling the LLM — a hit
    means the input hasn't changed since the last run, so Stage 3 skips the call.
    """

    __tablename__ = "extraction_staging"
    __table_args__ = (
        UniqueConstraint("ingredient_name", "input_hash", name="uq_staging_name_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ingredient_name: Mapped[str] = mapped_column(String(255), index=True)
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    raw_input: Mapped[dict] = mapped_column(JSONB)
    normalized_status: Mapped[str] = mapped_column(String(64))
    reasoning: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
