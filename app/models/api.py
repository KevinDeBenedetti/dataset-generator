from pydantic import BaseModel, Field, HttpUrl
from typing import Dict, List, Optional, Any, Union


class UrlEntry(BaseModel):
    """Un élément URL individuel avec sa description"""
    url: HttpUrl = Field(..., description="URL à scraper")
    description: Optional[str] = Field(None, description="Description de la source")


class ScrapingTask(BaseModel):
    """Tâche de scraping avec structure hiérarchique comme dans urls.json"""
    urls_config: Dict[str, Any] = Field(
        ...,
        description="Configuration d'URLs avec structure hiérarchique"
    )
    use_cache: bool = Field(
        True, 
        description="Utiliser le cache pour les URLs déjà scrapées"
    )
    target_language: Optional[str] = Field(
        None, 
        description="Langue cible pour les QA (par défaut: fr)"
    )


class SimpleUrlList(BaseModel):
    """Format simplifié pour une liste d'URLs à scraper"""
    urls: List[str] = Field(..., description="Liste simple d'URLs à scraper")
    category: str = Field("general", description="Catégorie pour toutes les URLs")
    use_cache: bool = Field(True, description="Utiliser le cache")


class ScrapingResult(BaseModel):
    """Résultat d'une tâche de scraping"""
    task_id: str = Field(..., description="ID unique de la tâche")
    status: str = Field(..., description="Statut: success, error, processing")
    urls_processed: int = Field(0, description="Nombre d'URLs traitées")
    qa_pairs_generated: int = Field(0, description="Nombre de paires QA générées")
    files_generated: List[str] = Field([], description="Chemins des fichiers générés")
    errors: List[str] = Field([], description="Erreurs éventuelles")
    
    
class TaskStatus(BaseModel):
    """Statut d'une tâche"""
    task_id: str
    status: str
    progress: float = Field(0.0, description="Progression de 0 à 1")
    details: Optional[ScrapingResult] = None
    message: Optional[str] = None
