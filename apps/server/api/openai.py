from fastapi import APIRouter, HTTPException

# Relative import to the LLM service (api/ -> ../services)
from server.services.llm import LLMService

router = APIRouter(prefix="/openai", tags=["openai"])


@router.get("/models")
def list_openai_models():
    """
    Returns the list of available models from the OpenAI API.
    """
    service = LLMService()
    models = service.get_models()
    if models is None:
        raise HTTPException(status_code=500, detail="Unable to retrieve OpenAI models")
    return {"models": models}
