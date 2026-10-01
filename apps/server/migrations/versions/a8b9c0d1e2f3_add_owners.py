"""datasets, job runs, model defaults and quality rules belong to a user

Revision ID: a8b9c0d1e2f3
Revises: f6a7b8c9d0e1
Create Date: 2026-09-30

Until now every row was global. This gives each one an owner:

* ``datasets.owner_id`` and ``job_runs.owner_id`` (FK ``users.id``, cascade);
  a dataset name is now unique *per owner*, and a job may have one active run
  *per owner*;
* ``model_defaults`` becomes ``(user_id, role)`` and ``quality_rules`` one row
  per ``user_id`` (it used to be a singleton ``id = 'default'``);
* ``datasets.qdrant_collection`` records the Qdrant collection an existing
  dataset already uses, so nothing has to be re-embedded (new datasets are
  named after their immutable id instead of a slug of their name).

Existing rows go to the oldest active admin; with no admin yet they go to an
inactive, passwordless ``system`` user (``python -m server.cli claim-legacy``
hands them to a real account later). No row is deleted.
"""

import os
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SYSTEM_EMAIL = "system@datasetgen.invalid"

# The account legacy rows are assigned to: the oldest active admin, else the
# system user created below.
_OWNER = (
    "COALESCE("
    "(SELECT id FROM users WHERE role = 'admin' AND is_active "
    "ORDER BY created_at NULLS LAST, id LIMIT 1), "
    f"(SELECT id FROM users WHERE email = '{SYSTEM_EMAIL}')"
    ")"
)

# services.qdrant.legacy_collection_name in SQL: lower-case, every run of
# characters outside [a-zA-Z0-9_-] becomes "_", surrounding "_" trimmed.
_LEGACY_SLUG = (
    "COALESCE(NULLIF(btrim(regexp_replace(lower(btrim(name)), "
    "'[^a-zA-Z0-9_-]+', '_', 'g'), '_'), ''), 'unnamed')"
)


def _has_legacy_rows() -> str:
    return " OR ".join(
        f"EXISTS (SELECT 1 FROM {t})"
        for t in ("datasets", "job_runs", "model_defaults", "quality_rules")
    )


def upgrade() -> None:
    """Upgrade schema."""
    # A home for legacy rows when there is no admin to own them.
    op.execute(
        sa.text(
            "INSERT INTO users (id, email, hashed_password, role, provider, is_active, created_at) "
            f"SELECT :id, '{SYSTEM_EMAIL}', NULL, 'user', 'system', FALSE, "
            "(NOW() AT TIME ZONE 'UTC') "
            "WHERE NOT EXISTS (SELECT 1 FROM users WHERE role = 'admin' AND is_active) "
            f"AND NOT EXISTS (SELECT 1 FROM users WHERE email = '{SYSTEM_EMAIL}') "
            f"AND ({_has_legacy_rows()})"
        ).bindparams(id=str(uuid4()))
    )

    # --- datasets ---------------------------------------------------------
    op.add_column("datasets", sa.Column("owner_id", sa.String(), nullable=True))
    op.add_column(
        "datasets", sa.Column("qdrant_collection", sa.String(), nullable=True)
    )
    op.execute(f"UPDATE datasets SET owner_id = {_OWNER}")
    # Existing datasets keep the collection they already have in Qdrant.
    prefix = os.environ.get("QDRANT_COLLECTION_PREFIX", "").strip() or "dataset_"
    op.execute(
        sa.text(
            f"UPDATE datasets SET qdrant_collection = :prefix || {_LEGACY_SLUG}"
        ).bindparams(prefix=prefix)
    )
    op.alter_column("datasets", "owner_id", nullable=False)
    op.create_foreign_key(
        "fk_datasets_owner_id_users",
        "datasets",
        "users",
        ["owner_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_datasets_owner_id", "datasets", ["owner_id"])
    # The name alone stops being unique: it is unique per owner.
    op.drop_index("ix_datasets_name", table_name="datasets")
    op.create_index("ix_datasets_name", "datasets", ["name"])
    op.create_unique_constraint(
        "uq_datasets_owner_name", "datasets", ["owner_id", "name"]
    )

    # --- job_runs ---------------------------------------------------------
    op.add_column("job_runs", sa.Column("owner_id", sa.String(), nullable=True))
    op.execute(f"UPDATE job_runs SET owner_id = {_OWNER}")
    op.alter_column("job_runs", "owner_id", nullable=False)
    op.create_foreign_key(
        "fk_job_runs_owner_id_users",
        "job_runs",
        "users",
        ["owner_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_job_runs_owner_id", "job_runs", ["owner_id"])
    op.drop_index("uq_job_runs_one_active", table_name="job_runs")
    op.create_index(
        "uq_job_runs_one_active",
        "job_runs",
        ["owner_id", "job_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )

    # --- model_defaults: PK role -> (user_id, role) -----------------------
    op.add_column("model_defaults", sa.Column("user_id", sa.String(), nullable=True))
    op.execute(f"UPDATE model_defaults SET user_id = {_OWNER}")
    op.drop_constraint("model_defaults_pkey", "model_defaults", type_="primary")
    op.alter_column("model_defaults", "user_id", nullable=False)
    op.create_primary_key("model_defaults_pkey", "model_defaults", ["user_id", "role"])
    op.create_foreign_key(
        "fk_model_defaults_user_id_users",
        "model_defaults",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # --- quality_rules: singleton id -> one row per user ------------------
    op.add_column("quality_rules", sa.Column("user_id", sa.String(), nullable=True))
    op.execute(f"UPDATE quality_rules SET user_id = {_OWNER}")
    op.drop_constraint("quality_rules_pkey", "quality_rules", type_="primary")
    op.drop_column("quality_rules", "id")
    op.alter_column("quality_rules", "user_id", nullable=False)
    op.create_primary_key("quality_rules_pkey", "quality_rules", ["user_id"])
    op.create_foreign_key(
        "fk_quality_rules_user_id_users",
        "quality_rules",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    """Downgrade schema.

    Best effort: what was per-user collapses back to a single global value (the
    most recently updated), and datasets of two owners sharing a name make the
    unique index on ``name`` fail — rename one first.
    """
    # quality_rules: keep the most recently updated row as the global one.
    op.drop_constraint(
        "fk_quality_rules_user_id_users", "quality_rules", type_="foreignkey"
    )
    op.execute(
        "DELETE FROM quality_rules WHERE user_id <> ("
        "SELECT user_id FROM quality_rules ORDER BY updated_at DESC NULLS LAST, user_id LIMIT 1)"
    )
    op.drop_constraint("quality_rules_pkey", "quality_rules", type_="primary")
    op.add_column(
        "quality_rules",
        sa.Column("id", sa.String(), nullable=False, server_default="default"),
    )
    op.alter_column("quality_rules", "id", server_default=None)
    op.create_primary_key("quality_rules_pkey", "quality_rules", ["id"])
    op.drop_column("quality_rules", "user_id")

    # model_defaults: keep one row per role (the most recently updated).
    op.drop_constraint(
        "fk_model_defaults_user_id_users", "model_defaults", type_="foreignkey"
    )
    op.execute(
        "DELETE FROM model_defaults a USING model_defaults b "
        "WHERE a.role = b.role AND a.ctid <> b.ctid AND ("
        "COALESCE(a.updated_at, 'epoch'::timestamp), a.user_id) < "
        "(COALESCE(b.updated_at, 'epoch'::timestamp), b.user_id)"
    )
    op.drop_constraint("model_defaults_pkey", "model_defaults", type_="primary")
    op.create_primary_key("model_defaults_pkey", "model_defaults", ["role"])
    op.drop_column("model_defaults", "user_id")

    # job_runs
    op.drop_index("uq_job_runs_one_active", table_name="job_runs")
    op.execute(
        "UPDATE job_runs SET status = 'interrupted' WHERE status = 'running' AND id NOT IN ("
        "SELECT DISTINCT ON (job_id) id FROM job_runs WHERE status = 'running' "
        "ORDER BY job_id, started_at DESC)"
    )
    op.create_index(
        "uq_job_runs_one_active",
        "job_runs",
        ["job_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )
    op.drop_index("ix_job_runs_owner_id", table_name="job_runs")
    op.drop_constraint("fk_job_runs_owner_id_users", "job_runs", type_="foreignkey")
    op.drop_column("job_runs", "owner_id")

    # datasets
    op.drop_constraint("uq_datasets_owner_name", "datasets", type_="unique")
    op.drop_index("ix_datasets_name", table_name="datasets")
    op.create_index("ix_datasets_name", "datasets", ["name"], unique=True)
    op.drop_index("ix_datasets_owner_id", table_name="datasets")
    op.drop_constraint("fk_datasets_owner_id_users", "datasets", type_="foreignkey")
    op.drop_column("datasets", "qdrant_collection")
    op.drop_column("datasets", "owner_id")
