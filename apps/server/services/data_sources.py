"""Data sources and recipes (ADR 0001): owner-scoped CRUD.

Another user's data source or recipe answers like an unknown one. Deleting a
data source deletes its recipes (cascade) and its uploaded files; deleting a
recipe deletes the draft files of its runs (services/draft_store.py).
"""

from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from server.core.config import config
from server.models.data_source import DataSource, Recipe
from server.models.job_run import JobRun

# The job a recipe runs as: its options carry the recipe it was run from.
RECIPE_JOB_ID = "recipe"


class NotFound(LookupError):
    """No data source or recipe with that id among the caller's."""


class Conflict(ValueError):
    """Another one of the caller's already has that name."""


class QuotaReached(ValueError):
    """The caller has as many as allowed."""


def _source_view(row: DataSource) -> Dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "connector": row.connector,
        "config": dict(row.config or {}),
        "secret_kind": row.secret_kind,
        "licence": row.licence,
        "last_fingerprint": row.last_fingerprint,
        "last_fetched_at": row.last_fetched_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _recipe_view(row: Recipe) -> Dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "data_source_id": row.data_source_id,
        "steps": list(row.steps or []),
        "output_kind": row.output_kind,
        "output_options": dict(row.output_options or {}),
        "target_repo": row.target_repo,
        "visibility": row.visibility,
        "model_ref": row.model_ref,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def owned_source(db: Session, owner_id: str, source_id: str) -> DataSource:
    row = db.scalar(
        select(DataSource).where(
            DataSource.id == source_id, DataSource.owner_id == owner_id
        )
    )
    if row is None:
        raise NotFound(f"Unknown data source '{source_id}'")
    return row


def owned_recipe(db: Session, owner_id: str, recipe_id: str) -> Recipe:
    row = db.scalar(
        select(Recipe).where(Recipe.id == recipe_id, Recipe.owner_id == owner_id)
    )
    if row is None:
        raise NotFound(f"Unknown recipe '{recipe_id}'")
    return row


def _commit(db: Session, what: str) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict(f"You already have a {what} with that name") from None


# --- data sources ----------------------------------------------------------


def list_sources(db: Session, owner_id: str) -> List[Dict[str, Any]]:
    rows = db.scalars(
        select(DataSource)
        .where(DataSource.owner_id == owner_id)
        .order_by(DataSource.updated_at.desc(), DataSource.id)
    )
    return [_source_view(r) for r in rows]


def get_source(db: Session, owner_id: str, source_id: str) -> Dict[str, Any]:
    return _source_view(owned_source(db, owner_id, source_id))


class InvalidConfig(ValueError):
    """A connector that doesn't exist, or a config its schema refuses."""


def check_config(connector: str, config_: Dict[str, Any], *, upload: bool = False):
    """``config_`` as ``connector`` validates it (ConnectorError-like messages)."""
    from pydantic import ValidationError

    from server.connectors import get_connector

    spec = get_connector(connector)
    if spec is None:
        raise InvalidConfig(f"Unknown connector '{connector}'")
    if getattr(spec.spec("en"), "created_by_upload", False) and not upload:
        raise InvalidConfig(
            "A file data source is created by uploading it (POST /data-sources/upload)"
        )
    try:
        return spec.config_model.model_validate(config_).model_dump()
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first.get("loc", ()))
        raise InvalidConfig(f"config.{where}: {first.get('msg')}") from None


def create_source(
    db: Session,
    owner_id: str,
    data: Dict[str, Any],
    *,
    secret_kind: Optional[str] = None,
    source_id: Optional[str] = None,
    upload: bool = False,
) -> Dict[str, Any]:
    data = {
        **data,
        "config": check_config(
            data["connector"], data.get("config") or {}, upload=upload
        ),
    }
    count = db.scalar(
        select(func.count())
        .select_from(DataSource)
        .where(DataSource.owner_id == owner_id)
    )
    if (count or 0) >= config.quota_data_sources:
        raise QuotaReached(
            f"You have {config.quota_data_sources} data sources, the most allowed"
        )
    row = DataSource(
        owner_id=owner_id,
        name=data["name"],
        connector=data["connector"],
        config=dict(data.get("config") or {}),
        licence=data.get("licence"),
        secret_kind=secret_kind,
    )
    if source_id:
        row.id = source_id
    db.add(row)
    _commit(db, "data source")
    db.refresh(row)
    return _source_view(row)


def update_source(
    db: Session, owner_id: str, source_id: str, changes: Dict[str, Any]
) -> Dict[str, Any]:
    row = owned_source(db, owner_id, source_id)
    if changes.get("config") is not None:
        # The file of an upload is already stored: its reading options may change.
        changes = {
            **changes,
            "config": check_config(row.connector, changes["config"], upload=True),
        }
    if changes.get("config") is not None and changes["config"] != (row.config or {}):
        # Other settings, other rows: the next scheduled run fetches again.
        row.last_fingerprint = None
    for key in ("name", "config", "licence"):
        if key in changes and changes[key] is not None:
            setattr(row, key, changes[key])
    _commit(db, "data source")
    db.refresh(row)
    return _source_view(row)


def delete_source(db: Session, owner_id: str, source_id: str) -> None:
    from server.services.draft_store import SOURCES_DIR, get_store

    row = owned_source(db, owner_id, source_id)
    recipe_ids = [
        r.id for r in db.scalars(select(Recipe).where(Recipe.data_source_id == row.id))
    ]
    for recipe_id in recipe_ids:
        _delete_run_files(db, owner_id, recipe_id)
    db.delete(row)
    db.commit()
    get_store().delete(owner_id, SOURCES_DIR, source_id)


# --- recipes ---------------------------------------------------------------


def list_recipes(db: Session, owner_id: str) -> List[Dict[str, Any]]:
    rows = db.scalars(
        select(Recipe)
        .where(Recipe.owner_id == owner_id)
        .order_by(Recipe.updated_at.desc(), Recipe.id)
    )
    return [_recipe_view(r) for r in rows]


def get_recipe(db: Session, owner_id: str, recipe_id: str) -> Dict[str, Any]:
    return _recipe_view(owned_recipe(db, owner_id, recipe_id))


def create_recipe(db: Session, owner_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    source = owned_source(db, owner_id, data["data_source_id"])  # 404 for another's
    preset_id = (
        (source.config or {}).get("preset") if source.connector == "rest" else None
    )
    if preset_id and not data.get("steps"):
        from server.connectors.presets import get_preset

        # A preset's first steps (Sirene: a sole trader's personal data dropped).
        preset = get_preset(preset_id)
        if preset is not None and preset.steps:
            data = {**data, "steps": [dict(s) for s in preset.steps]}
    count = db.scalar(
        select(func.count()).select_from(Recipe).where(Recipe.owner_id == owner_id)
    )
    if (count or 0) >= config.quota_recipes:
        raise QuotaReached(f"You have {config.quota_recipes} recipes, the most allowed")
    row = Recipe(owner_id=owner_id, **data)
    db.add(row)
    _commit(db, "recipe")
    db.refresh(row)
    return _recipe_view(row)


def update_recipe(
    db: Session, owner_id: str, recipe_id: str, changes: Dict[str, Any]
) -> Dict[str, Any]:
    row = owned_recipe(db, owner_id, recipe_id)
    for key, value in changes.items():
        if value is not None and hasattr(row, key) and key not in ("id", "owner_id"):
            setattr(row, key, value)
    _commit(db, "recipe")
    db.refresh(row)
    return _recipe_view(row)


def _recipe_runs(db: Session, owner_id: str, recipe_id: str) -> List[JobRun]:
    rows = db.scalars(
        select(JobRun).where(
            JobRun.owner_id == owner_id, JobRun.job_id == RECIPE_JOB_ID
        )
    )
    return [r for r in rows if (r.options or {}).get("recipe_id") == recipe_id]


def _delete_run_files(db: Session, owner_id: str, recipe_id: str) -> None:
    from server.services.draft_store import get_store

    store = get_store()
    for run in _recipe_runs(db, owner_id, recipe_id):
        store.delete(owner_id, run.id)


def delete_recipe(db: Session, owner_id: str, recipe_id: str) -> None:
    from server.models.job_schedule import JobSchedule

    row = owned_recipe(db, owner_id, recipe_id)
    _delete_run_files(db, owner_id, recipe_id)
    db.query(JobSchedule).filter(
        JobSchedule.owner_id == owner_id,
        JobSchedule.job_id == RECIPE_JOB_ID,
        JobSchedule.scope == recipe_id,
    ).delete(synchronize_session=False)
    db.delete(row)
    db.commit()


def export_rows(db: Session, owner_id: str) -> Dict[str, Any]:
    """What the account export lists: data sources and recipes, no secrets and
    no draft files."""
    return {
        "data_sources": list_sources(db, owner_id),
        "recipes": list_recipes(db, owner_id),
    }
