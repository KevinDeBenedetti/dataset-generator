"""Model providers (an OpenAI-compatible endpoint, the Claude subscription),
per-role defaults, and the default embedding."""

import time
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from server.core.config import config
from server.schemas.models import (
    ModelDefaultsUpdate,
    ModelsResponse,
    ModelTestRequest,
    ModelTestResponse,
)
from server.models.user import User
from server.api.deps import get_credentials
from server.services.auth import get_current_user
from server.services.credentials import Credentials
from server.services.model_defaults import (
    ROLES,
    get_model_defaults,
    update_model_defaults,
)
from server.services.providers import (
    PROVIDERS,
    CompletionRequest,
    ProviderError,
    complete,
    validate_ref,
)
from server.services.semantic import default_embedding_model

router = APIRouter(prefix="/models", tags=["models"])


async def _snapshot(discover: bool, user_id: str, creds: Credentials) -> ModelsResponse:
    providers = []
    for provider in PROVIDERS.values():
        if provider.name == "claude" and not config.claude_provider_available:
            continue  # development and CI only
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
    defaults = await run_in_threadpool(get_model_defaults, user_id)  # database
    on = config.semantic_enabled
    return ModelsResponse(
        providers=providers,
        defaults=defaults,
        roles=list(ROLES),
        embedding_model=default_embedding_model(creds) if on else "",
        local_embedding_model=config.semantic_model if on else "",
    )


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
    """Every provider with its status and models, plus your per-role defaults."""
    return await _snapshot(discover, user.id, creds)


@router.put("/defaults", response_model=ModelsResponse)
async def put_model_defaults(
    body: ModelDefaultsUpdate,
    user: User = Depends(get_current_user),
    creds: Credentials = Depends(get_credentials),
) -> ModelsResponse:
    """Set your default model for one or more roles."""
    try:
        await run_in_threadpool(update_model_defaults, user.id, body.defaults, creds)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
