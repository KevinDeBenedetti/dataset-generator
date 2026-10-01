"""Read-only view of the LLM prompts the application actually uses.

The prompts live in code (services/llm.py, services/agent.py) — this endpoint
surfaces them verbatim so the /prompts page shows the real thing rather than a
mock. Editing them stays a code change on purpose: they are tuned alongside
the parsing that consumes their output.
"""

from fastapi import APIRouter, Depends

from server.schemas.prompts import PromptInfo, PromptsResponse
from server.services.agent import QA_AGENT_INSTRUCTION
from server.services.llm import PromptManager
from server.models.user import User
from server.services.auth import get_current_user
from server.services.model_defaults import get_model_defaults

router = APIRouter(
    prefix="/prompts",
    tags=["prompts"],
)


@router.get("", response_model=PromptsResponse)
async def list_prompts(user: User = Depends(get_current_user)) -> PromptsResponse:
    """Every LLM prompt shipped with the app, with where/how it is used."""
    models = get_model_defaults(user.id)
    prompts = [
        PromptInfo(
            key="qa_agent",
            label="QA generation agent",
            role="system",
            model=models["qa"],
            used_by="Generation pipeline (every page/document) and /agent/qa-test",
            active=True,
            content=QA_AGENT_INSTRUCTION.strip(),
        ),
        PromptInfo(
            key="cleaning",
            label="Text cleaning",
            role="system",
            model=models["cleaning"],
            used_by="URL generation — cleans the fetched page text before QA",
            active=True,
            content=PromptManager.CLEANING_PROMPT.strip(),
        ),
        PromptInfo(
            key="extraction",
            label="Document transcription (VLM)",
            role="user",
            model=models["vision"],
            used_by="File uploads — transcribes PDF/image pages to Markdown",
            active=True,
            content=PromptManager.EXTRACTION_PROMPT.strip(),
        ),
    ]
    return PromptsResponse(total=len(prompts), prompts=prompts)
