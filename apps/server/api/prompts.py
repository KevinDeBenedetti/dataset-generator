"""Read-only view of the LLM prompts the application actually uses.

The prompts live in code (services/llm.py, services/agent.py) — this endpoint
surfaces them verbatim so the /prompts page shows the real thing rather than a
mock. Editing them stays a code change on purpose: they are tuned alongside
the parsing that consumes their output.
"""

from fastapi import APIRouter

from server.core.config import config
from server.schemas.prompts import PromptInfo, PromptsResponse
from server.services.agent import QA_AGENT_INSTRUCTION
from server.services.llm import PromptManager

router = APIRouter(
    prefix="/prompts",
    tags=["prompts"],
)


@router.get("", response_model=PromptsResponse)
async def list_prompts() -> PromptsResponse:
    """Every LLM prompt shipped with the app, with where/how it is used."""
    prompts = [
        PromptInfo(
            key="qa_agent",
            label="QA generation agent",
            role="system",
            model=config.model_qa,
            used_by="Generation pipeline (every page/document) and /agent/qa-test",
            active=True,
            content=QA_AGENT_INSTRUCTION.strip(),
        ),
        PromptInfo(
            key="cleaning",
            label="Text cleaning",
            role="system",
            model=config.model_cleaning,
            used_by="Generation pipeline — cleans scraped/extracted text before QA",
            active=True,
            content=PromptManager.CLEANING_PROMPT.strip(),
        ),
        PromptInfo(
            key="extraction",
            label="Document transcription (VLM)",
            role="user",
            model=config.openai_vlm_model,
            used_by="File uploads — transcribes PDF/image pages to Markdown",
            active=True,
            content=PromptManager.EXTRACTION_PROMPT.strip(),
        ),
        PromptInfo(
            key="qa_legacy",
            label="QA generation (legacy LLMService)",
            role="user",
            model=config.model_qa,
            used_by="Not used by the pipeline — superseded by the QA agent",
            active=False,
            content=PromptManager.get_qa_prompt(
                "{context}", "{target_language}"
            ).strip(),
        ),
    ]
    return PromptsResponse(total=len(prompts), prompts=prompts)
