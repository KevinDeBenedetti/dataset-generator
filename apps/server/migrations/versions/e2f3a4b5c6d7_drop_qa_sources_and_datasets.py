"""drop qa_sources and datasets

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-07-09 00:00:00.000000

`Dataset`/`QASource` have been superseded by Langfuse as the sole source of
truth for datasets and their Q/A pairs: `/langfuse/export` and
`/langfuse/preview` already read Langfuse directly (no more local-DB read),
and the generation pipeline's dedup pool + auto-sync now read/write Langfuse
too instead of `qa_sources`. Both tables are dead — written by nothing, read
by nothing — so they're dropped outright (no FK-drop dance needed first,
unlike the `page_snapshots` precedent: here the *referencing* table
(`qa_sources`) is the one being dropped, so its own FK goes with it).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, Sequence[str], None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index(op.f("ix_qa_sources_status"), table_name="qa_sources")
    op.drop_index(op.f("ix_qa_sources_dataset_name"), table_name="qa_sources")
    op.drop_index(op.f("ix_qa_sources_dataset_id"), table_name="qa_sources")
    op.drop_table("qa_sources")
    op.drop_table("datasets")


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table(
        "datasets",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("target_language", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "qa_sources",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("dataset_name", sa.String(), nullable=True),
        sa.Column("dataset_id", sa.String(), nullable=True),
        sa.Column("source_trace_id", sa.String(), nullable=True),
        sa.Column("page_snapshot_id", sa.String(), nullable=True),
        sa.Column("input", sa.JSON(), nullable=False),
        sa.Column("expected_output", sa.JSON(), nullable=False),
        sa.Column("qa_metadata", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("human_reviewed", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_qa_sources_dataset_id"), "qa_sources", ["dataset_id"], unique=False
    )
    op.create_index(
        op.f("ix_qa_sources_dataset_name"), "qa_sources", ["dataset_name"], unique=False
    )
    op.create_index(
        op.f("ix_qa_sources_status"), "qa_sources", ["status"], unique=False
    )
