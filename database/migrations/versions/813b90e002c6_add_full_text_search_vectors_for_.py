"""add full text search vectors for ingredients products warnings recalls

Revision ID: 813b90e002c6
Revises: 0e655f5fc4db
Create Date: 2026-07-29 22:52:32.495178

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '813b90e002c6'
down_revision: Union[str, Sequence[str], None] = '0e655f5fc4db'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Stored generated columns, not application-side triggers (DATABASE_DESIGN.md
    # Section 9) -- Postgres recomputes these automatically on every write, so
    # there's no trigger code to get out of sync with the underlying text.
    op.execute(
        "ALTER TABLE ingredient_versions ADD COLUMN search_vector tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english', name)) STORED"
    )
    op.execute(
        "CREATE INDEX ix_ingredient_versions_search_vector "
        "ON ingredient_versions USING gin (search_vector)"
    )

    op.execute(
        "ALTER TABLE product_versions ADD COLUMN search_vector tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english', name)) STORED"
    )
    op.execute(
        "CREATE INDEX ix_product_versions_search_vector "
        "ON product_versions USING gin (search_vector)"
    )

    op.execute(
        "ALTER TABLE warnings ADD COLUMN search_vector tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english', text)) STORED"
    )
    op.execute("CREATE INDEX ix_warnings_search_vector ON warnings USING gin (search_vector)")

    # Not called out explicitly in DATABASE_DESIGN.md Section 9's illustrative
    # list ("ingredient names, product names, warning text"), but ROADMAP.md
    # Brick 13 explicitly requires a /recalls search endpoint too -- reason
    # is the natural equivalent searchable field.
    op.execute(
        "ALTER TABLE recalls ADD COLUMN search_vector tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english', reason)) STORED"
    )
    op.execute("CREATE INDEX ix_recalls_search_vector ON recalls USING gin (search_vector)")

    # Aliases too: a keyword search for "Vitamin C" must find canonical
    # "Ascorbic Acid" once that synonym relationship is known (an Alias row,
    # per ENTITY_RESOLUTION.md) -- searching the canonical name alone won't.
    op.execute(
        "ALTER TABLE aliases ADD COLUMN search_vector tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english', alias_text)) STORED"
    )
    op.execute("CREATE INDEX ix_aliases_search_vector ON aliases USING gin (search_vector)")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_aliases_search_vector")
    op.execute("ALTER TABLE aliases DROP COLUMN IF EXISTS search_vector")

    op.execute("DROP INDEX IF EXISTS ix_recalls_search_vector")
    op.execute("ALTER TABLE recalls DROP COLUMN IF EXISTS search_vector")

    op.execute("DROP INDEX IF EXISTS ix_warnings_search_vector")
    op.execute("ALTER TABLE warnings DROP COLUMN IF EXISTS search_vector")

    op.execute("DROP INDEX IF EXISTS ix_product_versions_search_vector")
    op.execute("ALTER TABLE product_versions DROP COLUMN IF EXISTS search_vector")

    op.execute("DROP INDEX IF EXISTS ix_ingredient_versions_search_vector")
    op.execute("ALTER TABLE ingredient_versions DROP COLUMN IF EXISTS search_vector")
