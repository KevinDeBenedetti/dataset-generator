"""recreate datasets, qa_pairs and dataset_runs in postgres

Revision ID: b1c2d3e4f5a6
Revises: a7b8c9d0e1f2
Create Date: 2026-08-17

Brings dataset storage back into Postgres, which is now the sole source of
truth: Langfuse is gone from the project. This is not a revert of
``e2f3a4b5c6d7`` — the shapes differ on purpose. The old ``qa_sources`` mirrored
a Langfuse item (``input`` / ``expected_output`` / ``qa_metadata`` JSON blobs);
here the fields the app actually queries are real columns, so the Q/A list
paginates, the stats page aggregates and the sources view groups *in SQL*
instead of loading every pair into Python to count it. ``dataset_runs`` is new
altogether: the version history used to live in Langfuse runs.

No data migration: the previous store was left behind deliberately, so these
tables start empty.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "datasets",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("target_language", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    # Datasets are addressed by name everywhere (routes, front-end), so the
    # uniqueness is enforced here rather than assumed.
    op.create_index(op.f("ix_datasets_name"), "datasets", ["name"], unique=True)

    op.create_table(
        "qa_pairs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("dataset_id", sa.String(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=True),
        sa.Column("qa_metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_qa_pairs_dataset_id"), "qa_pairs", ["dataset_id"], unique=False
    )
    # The sources view groups by source_url, the list orders by created_at.
    op.create_index(
        op.f("ix_qa_pairs_source_url"), "qa_pairs", ["source_url"], unique=False
    )
    op.create_index(
        op.f("ix_qa_pairs_created_at"), "qa_pairs", ["created_at"], unique=False
    )

    op.create_table(
        "dataset_runs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("dataset_id", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("item_count", sa.Integer(), nullable=True),
        sa.Column("pages_analyzed", sa.Integer(), nullable=True),
        sa.Column("new_pairs", sa.Integer(), nullable=True),
        sa.Column("duplicates_skipped", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_id", "version", name="uq_run_version"),
    )
    op.create_index(
        op.f("ix_dataset_runs_dataset_id"), "dataset_runs", ["dataset_id"], unique=False
    )
    op.create_index(
        op.f("ix_dataset_runs_created_at"), "dataset_runs", ["created_at"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_dataset_runs_created_at"), table_name="dataset_runs")
    op.drop_index(op.f("ix_dataset_runs_dataset_id"), table_name="dataset_runs")
    op.drop_table("dataset_runs")
    op.drop_index(op.f("ix_qa_pairs_created_at"), table_name="qa_pairs")
    op.drop_index(op.f("ix_qa_pairs_source_url"), table_name="qa_pairs")
    op.drop_index(op.f("ix_qa_pairs_dataset_id"), table_name="qa_pairs")
    op.drop_table("qa_pairs")
    op.drop_index(op.f("ix_datasets_name"), table_name="datasets")
    op.drop_table("datasets")
