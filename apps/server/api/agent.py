"""Diagnostic endpoint to verify the QA agent in isolation.

Runs the agent on an arbitrary piece of text and returns both the raw model
response and the parsed QA pairs, so the agent can be validated without running
the full scrape/clean pipeline.
"""

import logging
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from server.core.config import config
from server.services.agent import QAAgentService

router = APIRouter(prefix="/agent", tags=["agent"])


class QAAgentTestRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Source text to feed the agent")
    target_language: Optional[str] = Field(
        None, description="Target language (defaults to server config)"
    )
    model: Optional[str] = Field(
        None, description="Model id (defaults to server config)"
    )


class QAAgentTestResponse(BaseModel):
    ok: bool = Field(..., description="True if at least one QA pair was parsed")
    model: str
    target_language: str
    count: int
    raw_length: int
    raw_response: str = Field(..., description="Exact text returned by the model")
    qa_pairs: List[Any] = Field(default_factory=list)
    error: Optional[str] = None


@router.post(
    "/qa-test",
    response_model=QAAgentTestResponse,
    summary="Run the QA agent on a text and return raw + parsed output",
)
async def qa_agent_test(request: QAAgentTestRequest) -> QAAgentTestResponse:
    model = request.model or config.model_qa
    if model and model not in config.available_models:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Model '{model}' not in available models: {config.available_models}",
        )

    service = QAAgentService()
    try:
        result = await service.generate_qa_debug(
            text=request.text,
            target_language=request.target_language,
            model=request.model,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logging.exception("ADK agent test failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agent run failed: {exc}",
        )

    return QAAgentTestResponse(ok=result["count"] > 0, **result)
