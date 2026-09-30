from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ModelInfoOut(BaseModel):
    ref: str = Field(..., description='"<provider>:<model>" reference')
    id: str
    provider: str
    label: str
    vision: bool


class ProviderOut(BaseModel):
    name: str
    label: str
    configured: bool
    missing_env: List[str] = Field(
        default_factory=list, description="Env vars to set to enable it"
    )
    models: List[ModelInfoOut]


class ModelsResponse(BaseModel):
    providers: List[ProviderOut]
    defaults: Dict[str, str] = Field(
        ..., description="Model reference per role (cleaning, qa, vision, jobs)"
    )
    roles: List[str]


class ModelDefaultsUpdate(BaseModel):
    defaults: Dict[str, str] = Field(
        ..., description="Roles to change, mapped to a model reference"
    )


class ModelTestRequest(BaseModel):
    ref: str = Field(..., description='Model reference, e.g. "claude:claude-sonnet-5"')
    prompt: str = Field(
        "Reply with one short sentence confirming you are reachable.",
        min_length=1,
        max_length=4000,
    )


class ModelTestResponse(BaseModel):
    ref: str
    ok: bool
    text: str = ""
    latency_ms: int
    usage: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
