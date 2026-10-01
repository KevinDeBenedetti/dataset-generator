"""at most one active run per job

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-09-30

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # A run still marked "running" when the schema changes belongs to a process
    # that is gone (runs live in the web process until the worker exists), and
    # would make the unique index below impossible to build.
    op.execute(
        "UPDATE job_runs SET status = 'interrupted', finished_at = NOW() "
        "WHERE status = 'running'"
    )
    op.create_index(
        "uq_job_runs_one_active",
        "job_runs",
        ["job_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("uq_job_runs_one_active", table_name="job_runs")
