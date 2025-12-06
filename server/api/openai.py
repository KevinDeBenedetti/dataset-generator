from fastapi import APIRouter, HTTPException

# import relatif vers le service LLM (api/ -> ../services)
from server.services.llm import LLMService

router = APIRouter(prefix="/openai", tags=["openai"])


@router.get("/models")
def list_openai_models():
    """
    Renvoie la liste des modèles disponibles depuis l'API OpenAI.
    """
    service = LLMService()
    models = service.get_models()
    if models is None:
        raise HTTPException(
            status_code=500, detail="Impossible de récupérer les modèles OpenAI"
        )
    return {"models": models}
