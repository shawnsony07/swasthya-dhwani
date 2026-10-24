"""add kill_switch_state table

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-25 01:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'kill_switch_state',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('changed_by', sa.String(length=128), nullable=True),
        sa.Column('changed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reason', sa.String(length=512), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('kill_switch_state')
