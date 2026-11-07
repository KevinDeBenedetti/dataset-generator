"""Dataset recipes: what a GitHub-fed dataset is generated from.

The GitHub page edits a recipe (its target Hugging Face repo and its public
GitHub sources); a generation reads it. Every accessor is owner-scoped: another
user's recipe answers like an unknown one.
"""

from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from server.core.config import config
from server.models.dataset_recipe import DatasetRecipe
from server.models.job_run import JobRun

# The job a recipe runs as (jobs/registry.py): off the Jobs page, started from
# POST /recipes/{id}/run, its options carry the recipe it was run from.
RECIPE_JOB_ID = "github-recipe"


class RecipeNotFoundError(LookupError):
    """No recipe with that id among the caller's."""


class RecipeConflictError(ValueError):
    """Another recipe of the caller already has that name."""


class RecipeQuotaError(ValueError):
    """The caller has as many recipes as allowed."""


def _latest_runs(db: Session, owner_id: str) -> Dict[str, Dict[str, str]]:
    """recipe id → its most recent run (``{"id", "status"}``)."""
    latest: Dict[str, Dict[str, str]] = {}
    rows = db.scalars(
        select(JobRun)
        .where(JobRun.owner_id == owner_id, JobRun.job_id == RECIPE_JOB_ID)
        .order_by(JobRun.started_at.desc())
    )
    for run in rows:
        recipe_id = (run.options or {}).get("recipe_id")
        if isinstance(recipe_id, str) and recipe_id not in latest:
            latest[recipe_id] = {"id": run.id, "status": run.status}
    return latest


def _view(
    recipe: DatasetRecipe, latest: Optional[Dict[str, Dict[str, str]]] = None
) -> Dict[str, Any]:
    return {
        "id": recipe.id,
        "name": recipe.name,
        "target_repo": recipe.target_repo,
        "include_profile": recipe.include_profile,
        "sources": list(recipe.sources or []),
        "model_ref": recipe.model_ref,
        "created_at": recipe.created_at,
        "updated_at": recipe.updated_at,
        "latest_run": (latest or {}).get(recipe.id),
    }


def _owned(db: Session, owner_id: str, recipe_id: str) -> DatasetRecipe:
    recipe = db.scalar(
        select(DatasetRecipe).where(
            DatasetRecipe.id == recipe_id, DatasetRecipe.owner_id == owner_id
        )
    )
    if recipe is None:
        raise RecipeNotFoundError(f"Unknown recipe '{recipe_id}'")
    return recipe


def _apply(recipe: DatasetRecipe, data: Dict[str, Any]) -> None:
    recipe.name = data["name"]
    recipe.target_repo = data["target_repo"]
    recipe.include_profile = bool(data.get("include_profile", True))
    recipe.sources = list(data.get("sources") or [])
    recipe.model_ref = data.get("model_ref") or None


def _commit(db: Session, name: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise RecipeConflictError(f"You already have a recipe named '{name}'") from exc


def list_recipes(db: Session, owner_id: str) -> List[Dict[str, Any]]:
    """The caller's recipes, most recently edited first."""
    rows = db.scalars(
        select(DatasetRecipe)
        .where(DatasetRecipe.owner_id == owner_id)
        .order_by(DatasetRecipe.updated_at.desc())
    )
    latest = _latest_runs(db, owner_id)
    return [_view(r, latest) for r in rows]


def get_recipe(db: Session, owner_id: str, recipe_id: str) -> Dict[str, Any]:
    return _view(_owned(db, owner_id, recipe_id), _latest_runs(db, owner_id))


def create_recipe(db: Session, owner_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    count = db.scalar(
        select(func.count())
        .select_from(DatasetRecipe)
        .where(DatasetRecipe.owner_id == owner_id)
    )
    if config.quota_recipes and (count or 0) >= config.quota_recipes:
        raise RecipeQuotaError(
            f"You already have {count} recipes (limit {config.quota_recipes}). "
            "Delete one first."
        )
    recipe = DatasetRecipe(owner_id=owner_id)
    _apply(recipe, data)
    db.add(recipe)
    _commit(db, data["name"])
    db.refresh(recipe)
    return _view(recipe)


def update_recipe(
    db: Session, owner_id: str, recipe_id: str, data: Dict[str, Any]
) -> Dict[str, Any]:
    recipe = _owned(db, owner_id, recipe_id)
    _apply(recipe, data)
    _commit(db, data["name"])
    db.refresh(recipe)
    return _view(recipe)


def delete_recipe(db: Session, owner_id: str, recipe_id: str) -> None:
    db.delete(_owned(db, owner_id, recipe_id))
    db.commit()
