from typing import List

from pydantic import BaseModel, Field


class PromptInfo(BaseModel):
    """One LLM prompt actually used (or shipped) by the application."""

    key: str = Field(..., description="Stable identifier")
    label: str = Field(..., description="Human-readable name")
    role: str = Field(..., description="Chat role the prompt is sent as")
    model: str = Field(..., description="Model (from config) the prompt targets")
    used_by: str = Field(..., description="Where in the app the prompt is used")
    active: bool = Field(
        ..., description="False for legacy prompts kept in the codebase but unused"
    )
    content: str = Field(..., description="The prompt text (templates verbatim)")


class PromptsResponse(BaseModel):
    total: int
    prompts: List[PromptInfo]
