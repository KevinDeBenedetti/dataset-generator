"""Model providers (OpenAI API, Claude subscription) and per-role defaults."""

import time
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query

from server.schemas.models import (
    ModelDefaultsUpdate,
    ModelsResponse,
    ModelTestRequest,
    ModelTestResponse,
)
from server.services.auth import require_admin
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

router = APIRouter(prefix="/models", tags=["models"])


async def _snapshot(discover: bool) -> ModelsResponse:
    providers = []
    for provider in PROVIDERS.values():
        models = await provider.list_models() if discover else provider.models()
        providers.append(
            {
                "name": provider.name,
                "label": provider.label,
                "configured": provider.configured(),
                "missing_env": provider.missing_env(),
                "models": [asdict(m) for m in models],
            }
        )
    return ModelsResponse(
        providers=providers, defaults=get_model_defaults(), roles=list(ROLES)
    )


@router.get("", response_model=ModelsResponse)
async def list_models(
    discover: bool = Query(
        False,
        description="Also ask the OpenAI-compatible endpoint which models it "
        "serves (a network call, 5 s max) on top of the configured ones",
    ),
) -> ModelsResponse:
    """Every provider with its status and models, plus the per-role defaults."""
    return await _snapshot(discover)


@router.put(
    "/defaults",
    response_model=ModelsResponse,
    dependencies=[Depends(require_admin)],
)
async def put_model_defaults(body: ModelDefaultsUpdate) -> ModelsResponse:
    """Set the default model of one or more roles (admin only)."""
    try:
        update_model_defaults(body.defaults)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return await _snapshot(discover=False)


@router.post(
    "/test",
    response_model=ModelTestResponse,
    # Spends provider quota (the Claude subscription included) — admin only.
    dependencies=[Depends(require_admin)],
)
async def test_model(body: ModelTestRequest) -> ModelTestResponse:
    """Send one short prompt to a model and report what came back."""
    try:
        ref = validate_ref(body.ref)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    started = time.perf_counter()
    try:
        result = await complete(
            ref, CompletionRequest(user=body.prompt, max_tokens=200)
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
