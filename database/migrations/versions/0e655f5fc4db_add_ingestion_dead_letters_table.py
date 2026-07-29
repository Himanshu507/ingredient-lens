"""add ingestion_dead_letters table

Revision ID: 0e655f5fc4db
Revises: 8331e5fc52fc
Create Date: 2026-07-29 22:39:28.768186

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0e655f5fc4db'
down_revision: Union[str, Sequence[str], None] = '8331e5fc52fc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'ingestion_dead_letters',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(length=64), nullable=False),
        sa.Column('run_id', sa.String(length=64), nullable=False),
        sa.Column(
            'stage',
            sa.Enum('validation', 'transform', 'save', name='deadletterstage', native_enum=False),
            nullable=False,
        ),
        sa.Column('record_identifier', sa.String(length=256), nullable=True),
        sa.Column('raw_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=False),
        sa.Column('reprocessed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_ingestion_dead_letters_source_stage',
        'ingestion_dead_letters',
        ['source', 'stage'],
        unique=False,
    )
    # NOTE: autogenerate also proposed dropping the three gin_trgm_ops indexes
    # from the entity-resolution migration (8331e5fc52fc) here -- a false
    # positive, since those are raw-SQL indexes (postgresql_ops isn't
    # expressible via the plain ORM Index() construct) and aren't reflected
    # in SQLAlchemy model metadata at all. Intentionally omitted.


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_ingestion_dead_letters_source_stage', table_name='ingestion_dead_letters')
    op.drop_table('ingestion_dead_letters')
