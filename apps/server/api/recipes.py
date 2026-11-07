"""Dataset recipes: the saved selection a GitHub-fed dataset is generated from.

Owner-scoped: another user's recipe answers 404, like an unknown one (see
tests/api/test_tenant_isolation.py).
"""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from server.api.deps import get_credentials
from server.core.database import get_db
from server.models.user import User
from server.schemas.jobs import JobRunOut
from server.schemas.recipes import RecipeIn, RecipeOut, RecipeRunRequest, RecipesOut
from server.services import recipes
from server.services.auth import get_current_user
from server.services.credentials import Credentials
from server.services.jobs import QuotaExceededError, RunConflictError, start_run

router = APIRouter(prefix="/recipes", tags=["recipes"])


def _not_found(exc: recipes.RecipeNotFoundError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


@router.get("", response_model=RecipesOut, summary="Your dataset recipes")
def get_recipes(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Your recipes, most recently edited first."""
    return {"recipes": recipes.list_recipes(db, user.id)}


@router.post(
    "",
    response_model=RecipeOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a recipe",
)
def post_recipe(
    body: RecipeIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return recipes.create_recipe(db, user.id, body.model_dump())
    except recipes.RecipeConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except recipes.RecipeQuotaError as e:
        raise HTTPException(status_code=429, detail=str(e)) from e


@router.get("/{recipe_id}", response_model=RecipeOut, summary="One recipe")
def get_recipe(
    recipe_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return recipes.get_recipe(db, user.id, recipe_id)
    except recipes.RecipeNotFoundError as e:
        raise _not_found(e) from e


@router.put("/{recipe_id}", response_model=RecipeOut, summary="Replace a recipe")
def put_recipe(
    recipe_id: str,
    body: RecipeIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Saves the whole recipe: the GitHub page sends it after every toggle."""
    try:
        return recipes.update_recipe(db, user.id, recipe_id, body.model_dump())
    except recipes.RecipeNotFoundError as e:
        raise _not_found(e) from e
    except recipes.RecipeConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.delete(
    "/{recipe_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a recipe"
)
def delete_recipe(
    recipe_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Deletes the recipe only: its Hugging Face dataset stays."""
    try:
        recipes.delete_recipe(db, user.id, recipe_id)
    except recipes.RecipeNotFoundError as e:
        raise _not_found(e) from e
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{recipe_id}/run",
    response_model=JobRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate a draft from a recipe",
)
async def run_recipe(
    recipe_id: str,
    body: RecipeRunRequest,
    user: User = Depends(get_current_user),
    creds: Credentials = Depends(get_credentials),
    db: Session = Depends(get_db),
):
    """Queue a generation of the recipe as it is now (a worker runs it): poll
    GET /jobs/runs/{id}, review the draft, then POST /jobs/runs/{id}/publish."""
    try:
        recipe = await run_in_threadpool(recipes.get_recipe, db, user.id, recipe_id)
    except recipes.RecipeNotFoundError as e:
        raise _not_found(e) from e
    options = {
        "recipe_id": recipe_id,
        # The recipe as it is now: what the run used, whatever edits follow.
        "recipe": RecipeIn.model_validate(recipe).model_dump(),
        "full_refresh": body.full_refresh,
    }
    model_ref = body.model_ref or recipe["model_ref"]
    try:
        run = await start_run(user.id, creds, recipes.RECIPE_JOB_ID, options, model_ref)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors(include_url=False)) from e
    except RunConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except QuotaExceededError as e:
        raise HTTPException(status_code=429, detail=str(e)) from e
    # An unusable model reference. After ValidationError, which subclasses it.
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return JobRunOut(**run)
