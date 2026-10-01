"""job runs become a queue served by workers

Revision ID: 2a3b4c5d6e7f
Revises: 1f2e3d4c5b6a
Create Date: 2026-10-01

* ``queued`` status; the one-active-run index now covers queued *and* running;
* worker bookkeeping: ``claimed_by``, ``claimed_at``, ``heartbeat_at``,
  ``progress``, ``cancel_requested``.

Runs left ``running`` by the in-process executor are marked ``interrupted``:
nothing would ever finish them.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2a3b4c5d6e7f"
down_revision: Union[str, Sequence[str], None] = "1f2e3d4c5b6a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("job_runs", sa.Column("claimed_by", sa.String(), nullable=True))
    op.add_column("job_runs", sa.Column("claimed_at", sa.DateTime(), nullable=True))
    op.add_column("job_runs", sa.Column("heartbeat_at", sa.DateTime(), nullable=True))
    op.add_column("job_runs", sa.Column("progress", sa.JSON(), nullable=True))
    op.add_column(
        "job_runs",
        sa.Column(
            "cancel_requested",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.execute(
        "UPDATE job_runs SET status = 'interrupted', "
        "finished_at = COALESCE(finished_at, (NOW() AT TIME ZONE 'UTC')) "
        "WHERE status = 'running'"
    )
    op.drop_index("uq_job_runs_one_active", table_name="job_runs")
    op.create_index(
        "uq_job_runs_one_active",
        "job_runs",
        ["owner_id", "job_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.create_index("ix_job_runs_status", "job_runs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_job_runs_status", table_name="job_runs")
    op.execute(
        "UPDATE job_runs SET status = 'interrupted' WHERE status IN ('queued', 'cancelled')"
    )
    op.drop_index("uq_job_runs_one_active", table_name="job_runs")
    op.create_index(
        "uq_job_runs_one_active",
        "job_runs",
        ["owner_id", "job_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )
    for column in (
        "cancel_requested",
        "progress",
        "heartbeat_at",
        "claimed_at",
        "claimed_by",
    ):
        op.drop_column("job_runs", column)
