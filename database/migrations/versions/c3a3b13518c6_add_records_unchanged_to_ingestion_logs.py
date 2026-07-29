"""add records_unchanged to ingestion_logs

Revision ID: c3a3b13518c6
Revises: 9e26dbd64cd1
Create Date: 2026-07-29 15:24:21.698009

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3a3b13518c6'
down_revision: Union[str, Sequence[str], None] = '9e26dbd64cd1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # server_default keeps this a safe additive change even against a
    # populated table, per ENGINEERING_PRINCIPLES.md's additive-migration rule.
    op.add_column(
        "ingestion_logs",
        sa.Column("records_unchanged", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("ingestion_logs", "records_unchanged")
