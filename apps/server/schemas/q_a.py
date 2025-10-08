from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class QAItem(BaseModel):
    """Modèle pour un élément Q&A individuel"""

    id: str = Field(..., description="ID unique de la question-réponse")
    question: str = Field(..., description="Question")
    answer: str = Field(..., description="Réponse")
    context: str = Field(..., description="Contexte source")
    source_url: Optional[str] = Field(None, description="URL source")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Niveau de confiance")
    created_at: datetime = Field(..., description="Date de création")
    metadata: Optional[Dict[str, Any]] = Field(
        None, description="Métadonnées additionnelles"
    )


class QAItemDetailed(QAItem):
    """Modèle pour un élément Q&A avec détails complets"""

    updated_at: Optional[datetime] = Field(
        None, description="Date de dernière modification"
    )
    dataset: Optional[Dict[str, Optional[str]]] = Field(
        None, description="Informations du dataset associé"
    )


class QAListResponse(BaseModel):
    """Modèle de réponse pour la liste des Q&A d'un dataset"""

    dataset_name: str = Field(..., description="Nom du dataset")
    dataset_id: str = Field(..., description="ID du dataset")
    total_count: int = Field(..., description="Nombre total d'éléments")
    returned_count: int = Field(..., description="Nombre d'éléments retournés")
    offset: int = Field(0, description="Décalage appliqué")
    limit: Optional[int] = Field(None, description="Limite appliquée")
    qa_data: List[QAItem] = Field(..., description="Liste des questions-réponses")


class QAResponse(BaseModel):
    """Modèle de réponse pour une Q&A individuelle"""

    id: str = Field(..., description="ID unique de la question-réponse")
    question: str = Field(..., description="Question")
    answer: str = Field(..., description="Réponse")
    context: str = Field(..., description="Contexte source")
    source_url: Optional[str] = Field(None, description="URL source")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Niveau de confiance")
    created_at: datetime = Field(..., description="Date de création")
    updated_at: Optional[datetime] = Field(
        None, description="Date de dernière modification"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        None, description="Métadonnées additionnelles"
    )
    dataset: Optional[Dict[str, Optional[str]]] = Field(
        None, description="Informations du dataset associé"
    )


class UnitQuestionAnswer(BaseModel):
    question: str = Field(..., description="The generated question")
    answer: str = Field(..., description="The generated answer")
    context: str = Field(
        ..., description="The context from which the question was generated"
    )
    confidence: float = Field(
        ...,
        description="The confidence score of the generated answer 0-1",
        ge=0.0,
        le=1.0,
    )


class UnitQuestionAnswerResponse(UnitQuestionAnswer):
    file_id: str
    dataset_id: str
