"""The model provider (an OpenAI-compatible endpoint), your LLM and the
embedding model."""

import logging
import time
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from server.schemas.models import (
    EmbeddingModelUpdate,
    ModelDefaultUpdate,
    ModelsResponse,
    ModelTestRequest,
    ModelTestResponse,
)
from server.models.user import User
from server.api.deps import get_credentials
from server.services.auth import get_current_user
from server.services.credentials import Credentials
from server.services.model_defaults import get_default_model, set_default_model
from server.services.providers import (
    PROVIDERS,
    CompletionRequest,
    ProviderError,
    complete,
    validate_ref,
)
from server.services import calibration
from server.services.semantic import (
    ENDPOINT_PREFIX,
    EmbeddingModelError,
    EndpointEmbedder,
    collection_models,
    default_embedding_model,
    embedding_choice,
)

router = APIRouter(prefix="/models", tags=["models"])
logger = logging.getLogger(__name__)


async def _snapshot(discover: bool, user_id: str, creds: Credentials) -> ModelsResponse:
    providers = []
    for provider in PROVIDERS.values():
        models = (
            await provider.list_models(creds) if discover else provider.models(creds)
        )
        providers.append(
            {
                "name": provider.name,
                "label": provider.label,
                "configured": provider.configured(creds),
                "missing": provider.missing(creds),
                "models": [asdict(m) for m in models],
                "embedding_models": [
                    asdict(m) for m in provider.embedding_models(creds)
                ],
                "endpoint": provider.endpoint(creds),
                "lent": provider.lent(creds),
            }
        )
    model = await run_in_threadpool(get_default_model, user_id)  # database
    return ModelsResponse(
        providers=providers,
        model=model,
        **await run_in_threadpool(_embedding_view, user_id, creds),  # database
    )


def _embedding_view(user_id: str, creds: Credentials) -> dict:
    """The embedding model the user's checks use, its thresholds and their
    measurement. Blocking (the database)."""
    choice = embedding_choice(creds)
    model_ref = default_embedding_model(creds)
    chosen = False
    report = None
    try:
        chosen = bool(calibration.load_choice(user_id, "")[0])
        report = calibration.calibration_report(user_id, model_ref)
    except Exception as exc:  # noqa: BLE001 — the page still shows the defaults
        logger.warning("Could not read the embedding choice: %s", exc)
    return {
        "embedding_model": model_ref,
        "embedding_chosen": chosen,
        "embedding_thresholds": asdict(choice.thresholds),
        "embedding_calibration": report if choice.measured else None,
    }


@router.get("", response_model=ModelsResponse)
async def list_models(
    discover: bool = Query(
        False,
        description="Also ask the OpenAI-compatible endpoint which models it "
        "serves (a network call, 5 s max) on top of the configured ones",
    ),
    user: User = Depends(get_current_user),
    creds: Credentials = Depends(get_credentials),
) -> ModelsResponse:
    """The provider with its status and models, your LLM and the embedding model."""
    return await _snapshot(discover, user.id, creds)


@router.put("/default", response_model=ModelsResponse)
async def put_default_model(
    body: ModelDefaultUpdate,
    user: User = Depends(get_current_user),
    creds: Credentials = Depends(get_credentials),
) -> ModelsResponse:
    """Set your LLM: the model of every step."""
    try:
        await run_in_threadpool(set_default_model, user.id, body.model, creds)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await _snapshot(False, user.id, creds)


@router.put("/embedding", response_model=ModelsResponse)
async def put_embedding_model(
    body: EmbeddingModelUpdate,
    user: User = Depends(get_current_user),
    creds: Credentials = Depends(get_credentials),
) -> ModelsResponse:
    """Measure an embedding model of your endpoint on the built-in test set,
    then use it, with its thresholds, for every check of your datasets."""
    ref = (
        body.model
        if body.model.startswith(ENDPOINT_PREFIX)
        else ENDPOINT_PREFIX + body.model
    )
    if ref not in {m.name for m in collection_models(creds)}:
        raise HTTPException(
            status_code=400,
            detail=f"'{body.model}' is not an embedding model of your endpoint",
        )
    embedder = EndpointEmbedder(ref.removeprefix(ENDPOINT_PREFIX), creds)
    try:
        report = await run_in_threadpool(calibration.measure, embedder)
    except EmbeddingModelError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await run_in_threadpool(calibration.save_choice, user.id, ref, report)
    return await _snapshot(False, user.id, creds)


@router.delete("/embedding", response_model=ModelsResponse)
async def delete_embedding_model(
    user: User = Depends(get_current_user),
    creds: Credentials = Depends(get_credentials),
) -> ModelsResponse:
    """Back to the server's embedding model (OPENAI_EMBEDDING_MODEL)."""
    await run_in_threadpool(calibration.reset_choice, user.id)
    return await _snapshot(False, user.id, creds)


@router.post(
    "/test",
    response_model=ModelTestResponse,
    # Spends the caller's own provider quota.
)
async def test_model(
    body: ModelTestRequest, creds: Credentials = Depends(get_credentials)
) -> ModelTestResponse:
    """Send one short prompt to a model and report what came back."""
    try:
        ref = validate_ref(body.ref, creds)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    started = time.perf_counter()
    try:
        result = await complete(
            ref, CompletionRequest(user=body.prompt, max_tokens=200), creds
        )
    except ProviderError as exc:
        return ModelTestResponse(
            ref=ref,
            ok=False,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error=str(exc),
        )
    return ModelTestResponse(
        ref=ref,
        ok=bool(result.text),
        text=result.text,
        latency_ms=int((time.perf_counter() - started) * 1000),
        usage=result.usage,
    )
