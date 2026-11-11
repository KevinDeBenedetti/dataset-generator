"""job schedules: a job's saved options per user, and when the worker runs it

Revision ID: 6e7f8091a2b3
Revises: 5d6e7f8091a2
Create Date: 2026-11-10

One row per owner, job and scope (a resume's id for the resume Q&A job): the
run's options, the model, an optional preset — every day, week or month at a
time (UTC) — and the next run's date, which the worker's sweep claims
(services/schedules.py). Deleting the user deletes their schedules.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6e7f8091a2b3"
down_revision: Union[str, Sequence[str], None] = "5d6e7f8091a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_schedules",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("owner_id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("model_ref", sa.String(), nullable=True),
        sa.Column("every", sa.String(), nullable=True),
        sa.Column("at_hour", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column(
            "at_minute", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "publish", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_run_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id", "job_id", "scope", name="uq_job_schedules_owner_job_scope"
        ),
    )
    op.create_index(
        op.f("ix_job_schedules_owner_id"), "job_schedules", ["owner_id"], unique=False
    )
    op.create_index(
        op.f("ix_job_schedules_next_run_at"),
        "job_schedules",
        ["next_run_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_job_schedules_next_run_at"), table_name="job_schedules")
    op.drop_index(op.f("ix_job_schedules_owner_id"), table_name="job_schedules")
    op.drop_table("job_schedules")
