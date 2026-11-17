"""job schedules: why the latest tick queued no run

Revision ID: a2b3c4d5e6f7
Revises: 91a2b3c4d5e6
Create Date: 2026-11-17

A schedule the worker cannot run — a model its endpoint stopped serving, a
quota reached, an owner no longer admin — is skipped at every tick, and only
the worker's log said so. ``skipped`` keeps the latest reason and its time,
so the schedule's page can show it; a queued run or a new save clears it.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "91a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("job_schedules", sa.Column("skipped", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("job_schedules", "skipped")
