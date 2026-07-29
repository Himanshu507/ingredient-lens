"""entity id sequences

Revision ID: 9e26dbd64cd1
Revises: 4a13a0735787
Create Date: 2026-07-29 14:34:14.298973

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9e26dbd64cd1'
down_revision: Union[str, Sequence[str], None] = '4a13a0735787'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Canonical entity IDs (e.g. `ING-000123`) are generated from dedicated
    # sequences rather than `SELECT MAX(...)+1` — sequences are safe under
    # concurrent inserts, `MAX+1` is not. See DATABASE_DESIGN.md Section 2.
    op.execute("CREATE SEQUENCE ingredient_id_seq")
    op.execute("CREATE SEQUENCE manufacturer_id_seq")
    op.execute("CREATE SEQUENCE product_id_seq")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP SEQUENCE product_id_seq")
    op.execute("DROP SEQUENCE manufacturer_id_seq")
    op.execute("DROP SEQUENCE ingredient_id_seq")
