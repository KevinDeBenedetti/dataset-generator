"""scope the qa_pairs primary key to the dataset

Revision ID: c3d4e5f6a7b8
Revises: b1c2d3e4f5a6
Create Date: 2026-09-27

Pair ids are content hashes that ignore the dataset, so with ``id`` alone as
the key, generating the same content into a second dataset re-parented the
existing row instead of adding one: the pair silently left the first dataset.
Keying on ``(dataset_id, id)`` makes each dataset own its rows. Pairs already
moved by the old behaviour cannot be recovered from the schema alone.
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint("qa_pairs_pkey", "qa_pairs", type_="primary")
    op.create_primary_key("qa_pairs_pkey", "qa_pairs", ["dataset_id", "id"])


def downgrade() -> None:
    """Downgrade schema.

    Fails if the same id now exists in two datasets — deliberately: collapsing
    them would mean choosing which dataset loses its pair.
    """
    op.drop_constraint("qa_pairs_pkey", "qa_pairs", type_="primary")
    op.create_primary_key("qa_pairs_pkey", "qa_pairs", ["id"])
