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
    missing: List[str] = Field(
        default_factory=list, description="What to add in Settings to enable it"
    )
    models: List[ModelInfoOut] = Field(..., description="The chat models")
    embedding_models: List[ModelInfoOut] = Field(
        default_factory=list,
        description="The embedding models (offered to the vector collections)",
    )
    endpoint: str = Field("", description="The host the calls go to")
    lent: bool = Field(
        False,
        description="The calls use the server's key and endpoint (no key of "
        "yours is saved)",
    )


class ModelsResponse(BaseModel):
    providers: List[ProviderOut]
    defaults: Dict[str, str] = Field(
        ..., description="Model reference per role (cleaning, qa, vision, jobs)"
    )
    roles: List[str]
    embedding_model: str = Field(
        "",
        description="What the duplicate and grounding checks embed with: "
        '"openai:<id>" (OPENAI_EMBEDDING_MODEL, on your endpoint) or a local model',
    )
    local_embedding_model: str = Field(
        "",
        description="The local model they fall back to ('' when the checks are off)",
    )


class ModelDefaultsUpdate(BaseModel):
    defaults: Dict[str, str] = Field(
        ..., description="Roles to change, mapped to a model reference"
    )


class ModelTestRequest(BaseModel):
    ref: str = Field(
        ..., description='Model reference, e.g. "claude:claude-sonnet-5-5"'
    )
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
