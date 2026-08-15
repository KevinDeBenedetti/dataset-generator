"""drop page_snapshots and cleaned_text

Revision ID: d1e2f3a4b5c6
Revises: c9d0e1f2a3b4
Create Date: 2026-07-08 00:00:00.000000

The scraper became stateless (no more crawl/clean caching in the DB) — these
two tables have been dead (written by nothing, read by nothing) since then.
`qa_sources.page_snapshot_id` always references them but is never actually
set to a real id anymore; its foreign key must be dropped before the target
table can go, so the column is kept (still nullable, just no longer FK-
constrained) rather than threading its removal through every call site that
still passes `page_snapshot_id=None`.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, Sequence[str], None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The original FK on qa_sources.page_snapshot_id was created unnamed, so its
# actual name is whatever Postgres auto-assigned (normally
# "qa_sources_page_snapshot_id_fkey"). Reflect it rather than hardcoding that
# spelling: a database restored from a dump, or one created back when this
# project still ran on SQLite, can carry a different name.
_FK_NAME = "qa_sources_page_snapshot_id_fkey"


def _reflected_fk_name() -> str | None:
    """Name of the qa_sources → page_snapshots FK, or None if already gone."""
    inspector = sa.inspect(op.get_bind())
    for fk in inspector.get_foreign_keys("qa_sources"):
        if fk.get("referred_table") == "page_snapshots":
            return fk.get("name")
    return None


def upgrade() -> None:
    """Upgrade schema."""
    fk_name = _reflected_fk_name()
    if fk_name:
        op.drop_constraint(fk_name, "qa_sources", type_="foreignkey")

    op.drop_table("cleaned_text")
    op.drop_index("ix_page_snapshots_url_hash", table_name="page_snapshots")
    op.drop_table("page_snapshots")


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table(
        "page_snapshots",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("user_agent", sa.String(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("url_hash", sa.String(), nullable=False),
        sa.Column("dataset_id", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_page_snapshots_url_hash", "page_snapshots", ["url_hash"], unique=False
    )
    op.create_table(
        "cleaned_text",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("page_snapshot_id", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("language", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["page_snapshot_id"], ["page_snapshots.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_foreign_key(
        _FK_NAME, "qa_sources", "page_snapshots", ["page_snapshot_id"], ["id"]
    )
