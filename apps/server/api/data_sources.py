"""Data sources (``/data-sources``) and recipes (``/recipes``) of the open-data
path (ADR 0001). Owner-scoped: another user's answers 404, like an unknown one
(tests/api/test_tenant_isolation.py)."""

import re
import shutil
import uuid
from typing import Any, Dict, List, Optional

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from server.connectors import REGISTRY
from server.connectors import sql_dump
from server.connectors.base import ConnectorError, ConnectorSpec, Limits
from server.connectors.upload import KIND as UPLOAD, describe, safe_name
from server.core.config import config
from server.core.i18n import request_locale

from server.core.database import get_db
from server.models.user import User
from server.schemas.data_sources import (
    DataSourceIn,
    DataSourceOut,
    DataSourcePatch,
    DataSourcesOut,
    SourceRecipeIn,
    SourceRecipeOut,
    SourceRecipePatch,
    SourceRecipesOut,
)
from server.api.deps import get_credentials
from server.schemas.jobs import JobRunOut
from server.schemas.recipes import RecipeScheduleIn, RecipeScheduleOut
from server.services import data_sources as service
from server.services.auth import get_current_user
from server.services.credentials import Credentials

sources_router = APIRouter(prefix="/data-sources", tags=["data sources"])
recipes_router = APIRouter(prefix="/recipes", tags=["recipes"])
connectors_router = APIRouter(prefix="/connectors", tags=["data sources"])


class ConnectorsOut(BaseModel):
    connectors: List[ConnectorSpec]


@connectors_router.get("", response_model=ConnectorsOut, summary="The connector kinds")
def list_connectors(locale: str = Depends(request_locale)):
    """What a data source can be: each connector's form, in your language."""
    return {"connectors": [c.spec(locale) for c in REGISTRY.values()]}


class CandidateOut(BaseModel):
    title: str
    description: str = ""
    config: Dict[str, Any]
    extra: Dict[str, Any] = Field(default_factory=dict)


class CandidatesOut(BaseModel):
    candidates: List[CandidateOut]


_discover_limiter = None


def _discover_limit(user_id: str) -> None:
    global _discover_limiter
    if _discover_limiter is None:
        from server.services.rate_limit import build_rate_limiter

        _discover_limiter = build_rate_limiter("connector_discover", 30, 60)
    wait = _discover_limiter.retry_after(user_id)
    if wait > 0:
        raise HTTPException(
            status_code=429,
            detail="Too many attempts — try again shortly.",
            headers={"Retry-After": str(int(wait) + 1)},
        )
    _discover_limiter.register_failure(user_id)


@connectors_router.get(
    "/{kind}/discover", response_model=CandidatesOut, summary="Search a connector"
)
async def discover(
    kind: str,
    q: str = Query(..., min_length=2, max_length=200),
    user: User = Depends(get_current_user),
    creds: Credentials = Depends(get_credentials),
):
    """What a connector finds for ``q`` (data.gouv.fr: datasets and their
    readable resources). 30 searches a minute."""
    connector = REGISTRY.get(kind)
    if connector is None or not hasattr(connector, "discover"):
        raise HTTPException(status_code=404, detail=f"No search for '{kind}'")
    await run_in_threadpool(_discover_limit, user.id)
    try:
        found = await connector.discover(q, creds)  # ty: ignore[call-non-callable]
    except ConnectorError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "candidates": [
            {
                "title": c.title,
                "description": c.description,
                "config": c.config,
                "extra": c.extra,
            }
            for c in found
        ]
    }


class PresetOut(BaseModel):
    id: str
    title: str
    description: str
    producer: str
    licence: str
    docs_url: str
    rate_limit_per_s: float
    max_records: Optional[int] = None
    needs_key: bool
    key_url: Optional[str] = None
    form_schema: Dict[str, Any]
    steps: List[Dict[str, Any]]


class PresetsOut(BaseModel):
    presets: List[PresetOut]


class PresetConfigOut(BaseModel):
    name: str
    licence: str
    config: Dict[str, Any]
    needs_key: bool


@connectors_router.get(
    "/rest/presets", response_model=PresetsOut, summary="French public API presets"
)
def list_presets(user: User = Depends(get_current_user)):
    """Ready-made REST data sources (Géo API, API Adresse, Annuaire de
    l'administration, Sirene): their form, licence and rate limit."""
    from server.connectors.presets import presets

    return {"presets": [p.describe() for p in presets().values()]}


@connectors_router.post(
    "/rest/presets/{preset_id}",
    response_model=PresetConfigOut,
    summary="A preset's REST config",
)
def preset_config(
    preset_id: str,
    params: Dict[str, Any] = Body(default_factory=dict),
    user: User = Depends(get_current_user),
):
    """The ``rest`` config, name and licence a preset makes of its form's
    values; ``POST /data-sources`` then adds it (nothing is saved here)."""
    from pydantic import ValidationError

    from server.connectors.presets import get_preset
    from server.connectors.rest import RestConfig

    preset = get_preset(preset_id)
    if preset is None:
        raise HTTPException(status_code=404, detail=f"No preset '{preset_id}'")
    try:
        config_ = preset.config(params)
        form = preset.form.model_validate(params)
        RestConfig.model_validate(config_)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first.get("loc", ()))
        raise HTTPException(
            status_code=422, detail=f"{where}: {first.get('msg')}"
        ) from None
    return {
        "name": preset.name(form)[:100],
        "licence": preset.licence,
        "config": config_,
        "needs_key": preset.key_header is not None,
    }


@connectors_router.get(
    "/datagouv/resources/{resource_id}/profile",
    summary="A data.gouv.fr resource's profile",
)
async def datagouv_profile(resource_id: str, user: User = Depends(get_current_user)):
    """The tabular API's profile of a resource (header, column formats,
    encoding, separator), shown before the data source is made."""
    from server.connectors.datagouv import DatagouvConnector

    if not re.fullmatch(r"[A-Za-z0-9-]{1,64}", resource_id):
        raise HTTPException(status_code=422, detail="Not a resource id")
    await run_in_threadpool(_discover_limit, user.id)
    try:
        return await DatagouvConnector().profile(resource_id)
    except ConnectorError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, service.NotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, service.Conflict):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, service.QuotaReached):
        return HTTPException(status_code=429, detail=str(exc))
    if isinstance(exc, (service.InvalidConfig, ConnectorError)):
        return HTTPException(status_code=422, detail=str(exc))
    raise exc


_ERRORS = (
    service.NotFound,
    service.Conflict,
    service.QuotaReached,
    service.InvalidConfig,
    ConnectorError,
)


@sources_router.get("", response_model=DataSourcesOut, summary="Your data sources")
def list_sources(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"data_sources": service.list_sources(db, user.id)}


@sources_router.post(
    "",
    response_model=DataSourceOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a data source",
)
def create_source(
    body: DataSourceIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return service.create_source(db, user.id, body.model_dump())
    except _ERRORS as exc:
        raise _error(exc) from exc


def _store_upload(owner_id: str, source_id: str, file: UploadFile, overrides):
    """Stream the upload into the data source's folder, then sniff it. Blocking:
    run in the threadpool."""
    from server.services.draft_store import (
        SOURCES_DIR,
        DraftQuotaExceeded,
        TooLarge,
        get_store,
    )

    store = get_store()
    filename = file.filename or "file"
    key = f"{SOURCES_DIR}/{source_id}/{safe_name(filename)}"
    try:
        path = store.write_stream(
            owner_id, key, file.file, config.data_upload_max_bytes
        )
    except TooLarge:
        raise HTTPException(
            status_code=413,
            detail=f"The file is larger than {config.data_upload_max_bytes // 1024**2} MB",
        ) from None
    except DraftQuotaExceeded:
        raise HTTPException(
            status_code=429, detail="Your storage for data is full: delete some drafts"
        ) from None
    try:
        if sql_dump.is_dump(filename):
            # Loaded once in a throwaway folder, to list its tables.
            work = store.path(owner_id, SOURCES_DIR, source_id, "describe")
            try:
                return sql_dump.KIND, sql_dump.describe(
                    path,
                    filename,
                    work,
                    Limits(config.data_upload_max_bytes, config.engine_timeout_s),
                )
            finally:
                shutil.rmtree(work, ignore_errors=True)
        return UPLOAD, describe(path, filename, overrides)
    except BaseException:
        store.delete(owner_id, SOURCES_DIR, source_id)
        raise


@sources_router.post(
    "/upload",
    response_model=DataSourceOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a data source from a file",
)
async def upload_source(
    file: UploadFile = File(
        ...,
        description="CSV, TSV, JSON, JSONL, Parquet, XLSX, or a .sql / .sql.gz dump",
    ),
    name: str = Form(..., min_length=1, max_length=100),
    licence: Optional[str] = Form(None, max_length=200),
    format: Optional[str] = Form(None, pattern=r"^(csv|tsv|json|jsonl|parquet|xlsx)$"),
    delimiter: Optional[str] = Form(None, min_length=1, max_length=1),
    encoding: Optional[str] = Form(None, max_length=32),
    sheet: Optional[str] = Form(None, max_length=100),
    json_path: Optional[str] = Form(None, max_length=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The file is streamed into your storage (at most ``UPLOAD_MAX_BYTES``) and
    recognised: format by its first bytes (a file that contradicts its name is
    refused), encoding and delimiter for text. The form's values override what
    was detected."""
    from server.services.draft_store import SOURCES_DIR, get_store

    if not name.strip():
        raise HTTPException(status_code=422, detail="name must not be blank")
    source_id = uuid.uuid4().hex
    overrides = {
        "format": format,
        "delimiter": delimiter,
        "encoding": encoding,
        "sheet": sheet,
        "json_path": json_path,
    }
    try:
        connector, described = await run_in_threadpool(
            _store_upload, user.id, source_id, file, overrides
        )
        return await run_in_threadpool(
            service.create_source,
            db,
            user.id,
            {
                "name": name.strip(),
                "connector": connector,
                "config": described,
                "licence": (licence or "").strip() or None,
            },
            source_id=source_id,
            upload=True,
        )
    except _ERRORS as exc:
        get_store().delete(user.id, SOURCES_DIR, source_id)
        raise _error(exc) from exc


class SourceSecretIn(BaseModel):
    value: str = Field(..., min_length=1, max_length=4096)


class SourceSecretOut(BaseModel):
    configured: bool


def _secret_kind(db: Session, owner_id: str, source_id: str) -> str:
    """The ``user_secrets`` kind of a data source's own secret (its connector's
    prefix + the source id); 404 for another user's, 422 when it takes none."""
    from server.connectors import get_connector

    row = service.owned_source(db, owner_id, source_id)
    connector = get_connector(row.connector)
    template = connector.spec("en").secret_kind if connector else None
    if not template or not template.endswith("<data_source_id>"):
        raise service.InvalidConfig("This data source takes no secret")
    return template.replace("<data_source_id>", row.id)


@sources_router.put(
    "/{source_id}/secret",
    response_model=SourceSecretOut,
    summary="Save the data source's secret",
)
def put_source_secret(
    source_id: str,
    body: SourceSecretIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The header value or API key the connector sends: stored encrypted,
    write-only (no route returns it)."""
    from server.services import user_secrets

    try:
        kind = _secret_kind(db, user.id, source_id)
        user_secrets.set_secret(user.id, kind, body.value)
    except _ERRORS as exc:
        raise _error(exc) from exc
    except user_secrets.SecretError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    row = service.owned_source(db, user.id, source_id)
    row.secret_kind = kind
    db.commit()
    return {"configured": True}


@sources_router.delete(
    "/{source_id}/secret",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Forget the data source's secret",
)
def delete_source_secret(
    source_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    from server.services import user_secrets

    try:
        kind = _secret_kind(db, user.id, source_id)
    except _ERRORS as exc:
        raise _error(exc) from exc
    user_secrets.delete_secret(user.id, kind)
    row = service.owned_source(db, user.id, source_id)
    row.secret_kind = None
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class SourceTestOut(BaseModel):
    records: int
    columns: List[str]
    sample: List[Dict[str, Any]]


@sources_router.post(
    "/{source_id}/test",
    response_model=SourceTestOut,
    summary="Try a data source's first page",
)
async def test_source(
    source_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The first page of a REST data source: the records and columns found."""
    from server.connectors import get_connector

    try:
        row = await run_in_threadpool(service.get_source, db, user.id, source_id)
    except _ERRORS as exc:
        raise _error(exc) from exc
    connector = get_connector(row["connector"])
    if connector is None or not hasattr(connector, "test"):
        raise HTTPException(status_code=422, detail="This data source has no test")
    await run_in_threadpool(_discover_limit, user.id)
    try:
        return await connector.test(user.id, source_id, row["config"])  # ty: ignore[call-non-callable]
    except ConnectorError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@sources_router.get("/{source_id}", response_model=DataSourceOut)
def get_source(
    source_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return service.get_source(db, user.id, source_id)
    except _ERRORS as exc:
        raise _error(exc) from exc


@sources_router.patch("/{source_id}", response_model=DataSourceOut)
def patch_source(
    source_id: str,
    body: DataSourcePatch,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return service.update_source(
            db, user.id, source_id, body.model_dump(exclude_unset=True)
        )
    except _ERRORS as exc:
        raise _error(exc) from exc


@sources_router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(
    source_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    try:
        service.delete_source(db, user.id, source_id)
    except _ERRORS as exc:
        raise _error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@recipes_router.get("", response_model=SourceRecipesOut, summary="Your recipes")
def list_recipes(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"recipes": service.list_recipes(db, user.id)}


@recipes_router.post(
    "",
    response_model=SourceRecipeOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a recipe",
)
def create_recipe(
    body: SourceRecipeIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return service.create_recipe(db, user.id, body.model_dump())
    except _ERRORS as exc:
        raise _error(exc) from exc


@recipes_router.get("/{recipe_id}", response_model=SourceRecipeOut)
def get_recipe(
    recipe_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return service.get_recipe(db, user.id, recipe_id)
    except _ERRORS as exc:
        raise _error(exc) from exc


@recipes_router.patch("/{recipe_id}", response_model=SourceRecipeOut)
def patch_recipe(
    recipe_id: str,
    body: SourceRecipePatch,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return service.update_recipe(
            db, user.id, recipe_id, body.model_dump(exclude_unset=True)
        )
    except _ERRORS as exc:
        raise _error(exc) from exc


@recipes_router.delete("/{recipe_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recipe(
    recipe_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    try:
        service.delete_recipe(db, user.id, recipe_id)
    except _ERRORS as exc:
        raise _error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class PreviewRequest(BaseModel):
    steps: Optional[List[Dict[str, Any]]] = Field(
        None, max_length=100, description="Draft steps to try; null = the recipe's own"
    )


class PreviewError(BaseModel):
    step: Optional[int] = Field(None, description="The failing step (0-based), if one")
    message: str


class PreviewOut(BaseModel):
    source_rows: int
    rows: int
    schema_: List[Dict[str, str]] = Field(alias="schema")
    step_rows: List[int]
    source_schema: List[Dict[str, str]] = Field(
        default_factory=list, description="The data source's columns, before any step"
    )
    step_schemas: List[List[Dict[str, str]]] = Field(
        default_factory=list, description="The columns after each step"
    )
    sample: List[Dict[str, Any]]
    pairs: Optional[List[Dict[str, Any]]] = Field(
        None, description="A facts recipe: the pairs of the first 20 rows"
    )
    llm: Optional[Dict[str, Any]] = Field(
        None,
        description="A model recipe: groups, estimated tokens, the token limit, "
        "the first source's text, and the missing setting if any",
    )
    error: Optional[PreviewError] = None

    model_config = {"populate_by_name": True}


_preview_limiter = None


def _limiter():
    global _preview_limiter
    if _preview_limiter is None:
        from server.services.rate_limit import build_rate_limiter

        _preview_limiter = build_rate_limiter("recipe_preview", 30, 60)
    return _preview_limiter


@recipes_router.post(
    "/{recipe_id}/preview",
    response_model=PreviewOut,
    response_model_by_alias=True,
    summary="The recipe's first rows",
)
async def preview_recipe(
    recipe_id: str,
    body: PreviewRequest,
    user: User = Depends(get_current_user),
    creds: Credentials = Depends(get_credentials),
):
    """The first 100 rows after the steps (the body's, to try them before
    saving), the output schema, the rows after each step, and the first
    failing step. 30 previews a minute."""
    from server.services.recipe_runs import RecipeRunError, preview_recipe as run

    limiter = _limiter()
    wait = await run_in_threadpool(limiter.retry_after, user.id)
    if wait > 0:
        raise HTTPException(
            status_code=429,
            detail="Too many attempts — try again shortly.",
            headers={"Retry-After": str(int(wait) + 1)},
        )
    await run_in_threadpool(limiter.register_failure, user.id)
    try:
        return await run(creds, recipe_id, body.steps)
    except service.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RecipeRunError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@recipes_router.post(
    "/{recipe_id}/run",
    response_model=JobRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run a recipe into a draft",
)
async def run_recipe(
    recipe_id: str,
    user: User = Depends(get_current_user),
    creds: Credentials = Depends(get_credentials),
    db: Session = Depends(get_db),
):
    """Queue a run (a worker fetches, loads and applies the steps): follow it
    with GET /jobs/runs/{id}; its draft is reviewed before publication."""
    from server.services.jobs import QuotaExceededError, RunConflictError, start_run

    try:
        await run_in_threadpool(service.get_recipe, db, user.id, recipe_id)
    except service.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        run = await start_run(user.id, creds, "recipe", {"recipe_id": recipe_id})
    except RunConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except QuotaExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    return JobRunOut(**run)


# --- a recipe's schedule (#314) --------------------------------------------------


def _schedule_out(saved: dict) -> dict:
    return {
        "recipe_id": saved["scope"],
        "every": saved["every"],
        "at_hour": saved["at_hour"],
        "at_minute": saved["at_minute"],
        "publish": saved["publish"],
        "next_run_at": saved["next_run_at"],
        "latest_run": saved["last_run"],
        "skipped": saved["skipped"],
        "updated_at": saved["updated_at"],
    }


@recipes_router.get(
    "/{recipe_id}/schedule",
    response_model=RecipeScheduleOut,
    summary="The recipe's schedule",
)
def get_recipe_schedule(
    recipe_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """When the recipe refreshes by itself; 404 until one is saved."""
    from server.services import schedules

    try:
        service.get_recipe(db, user.id, recipe_id)
        return _schedule_out(
            schedules.get_schedule(db, user.id, service.RECIPE_JOB_ID, recipe_id)
        )
    except service.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except schedules.ScheduleNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Recipe '{recipe_id}' has no schedule yet"
        ) from None


@recipes_router.put(
    "/{recipe_id}/schedule",
    response_model=RecipeScheduleOut,
    summary="Save the recipe's schedule",
)
def put_recipe_schedule(
    recipe_id: str,
    body: RecipeScheduleIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """At each due time the data source's fingerprint is checked first: an
    unchanged source starts no run (the schedule says so); a changed one runs
    the recipe, and publishes when ``publish`` is on and no blocking rule
    fails — else the draft waits for review."""
    from server.services import schedules

    try:
        recipe = service.get_recipe(db, user.id, recipe_id)
        saved = schedules.upsert_schedule(
            db,
            user.id,
            service.RECIPE_JOB_ID,
            recipe_id,
            options={"recipe_id": recipe_id},
            model_ref=recipe["model_ref"],
            every=body.every,
            at_hour=body.at_hour,
            at_minute=body.at_minute,
            publish=body.publish,
        )
    except service.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except schedules.ScheduleInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _schedule_out(saved)


@recipes_router.delete(
    "/{recipe_id}/schedule",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove the recipe's schedule",
)
def delete_recipe_schedule(
    recipe_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    from server.services import schedules

    try:
        service.get_recipe(db, user.id, recipe_id)
        schedules.delete_schedule(db, user.id, service.RECIPE_JOB_ID, recipe_id)
    except service.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except schedules.ScheduleNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Recipe '{recipe_id}' has no schedule yet"
        ) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
