from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ModelInfoOut(BaseModel):
    ref: str = Field(..., description='"<provider>:<model>" reference')
    id: str
    provider: str
    label: str


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
    model: str = Field(
        "",
        description="Your LLM, for every step: the one you saved, else "
        "OPENAI_LLM_MODEL",
    )
    embedding_model: str = Field(
        "",
        description="What the duplicate and grounding checks embed with: "
        '"openai:<id>" (OPENAI_EMBEDDING_MODEL, on your endpoint), "" without one',
    )


class ModelDefaultUpdate(BaseModel):
    model: str = Field(
        ..., max_length=200, description='Model reference, e.g. "openai:chat-default"'
    )


class ModelTestRequest(BaseModel):
    ref: str = Field(..., description='Model reference, e.g. "openai:chat-default"')
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
