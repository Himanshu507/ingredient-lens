"""enable pg_trgm and add trigram indexes for fuzzy matching

Revision ID: 8331e5fc52fc
Revises: c3a3b13518c6
Create Date: 2026-07-29 22:27:47.381544

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8331e5fc52fc'
down_revision: Union[str, Sequence[str], None] = 'c3a3b13518c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Strategy 3 (ENTITY_RESOLUTION.md Section 6): trigram candidate
    # generation against existing canonical names and aliases.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.execute(
        "CREATE INDEX ix_ingredient_versions_normalized_name_trgm "
        "ON ingredient_versions USING gin (normalized_name gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_manufacturer_versions_normalized_name_trgm "
        "ON manufacturer_versions USING gin (normalized_name gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_aliases_normalized_alias_text_trgm "
        "ON aliases USING gin (normalized_alias_text gin_trgm_ops)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_aliases_normalized_alias_text_trgm")
    op.execute("DROP INDEX IF EXISTS ix_manufacturer_versions_normalized_name_trgm")
    op.execute("DROP INDEX IF EXISTS ix_ingredient_versions_normalized_name_trgm")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
