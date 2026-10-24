"""add triage_snapshot to tasks

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-24 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tasks', sa.Column('triage_snapshot', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('tasks', 'triage_snapshot')
