import uuid
import os
import logging
from fastapi import APIRouter, HTTPException, BackgroundTasks
from app.models.api import ScrapingTask, SimpleUrlList, ScrapingResult, TaskStatus
from app.pipeline import ScrapingPipeline

router = APIRouter(
    prefix="/scrape",
    tags=["scrape"],
)

tasks_store = {}

@router.post("/urls", response_model=TaskStatus)
async def scrape_urls(task: ScrapingTask, background_tasks: BackgroundTasks):
    """
    Lance une tâche de scraping avec une configuration hiérarchique d'URLs
    similaire au format urls.json
    """
    task_id = str(uuid.uuid4())
    
    # Stocker la tâche avec statut initial
    tasks_store[task_id] = TaskStatus(
        task_id=task_id,
        status="processing",
        progress=0.0
    )
    
    # Définir la fonction de traitement en arrière-plan
    def process_task():
        try:
            # Remplacer la langue cible si spécifiée
            if task.target_language:
                os.environ["TARGET_LANGUAGE"] = task.target_language
                
            # Exécuter le pipeline
            pipeline = ScrapingPipeline(use_cache=task.use_cache)
            paths = pipeline.process_urls(task.urls_config)
            
            # Mettre à jour le statut avec le résultat
            tasks_store[task_id].status = "completed"
            tasks_store[task_id].progress = 1.0
            tasks_store[task_id].details = pipeline.create_result(task_id, paths)
            
        except Exception as e:
            logging.error(f"Erreur lors du traitement de la tâche {task_id}: {str(e)}")
            tasks_store[task_id].status = "error"
            tasks_store[task_id].details = ScrapingResult(
                task_id=task_id,
                status="error",
                errors=[f"Erreur: {str(e)}"]
            )
    
    # Lancer la tâche en arrière-plan
    background_tasks.add_task(process_task)
    
    return tasks_store[task_id]

@router.post("/simple", response_model=TaskStatus)
async def scrape_simple(task: SimpleUrlList, background_tasks: BackgroundTasks):
    """
    Version simplifiée pour scraper une liste d'URLs sans structure hiérarchique
    """
    task_id = str(uuid.uuid4())
    
    # Stocker la tâche avec statut initial
    tasks_store[task_id] = TaskStatus(
        task_id=task_id,
        status="processing",
        progress=0.0
    )
    
    # Fonction pour transformer la liste simple en structure hiérarchique
    def process_simple_task():
        try:
            # Convertir la liste simple en format hiérarchique
            urls_config = {
                task.category: {
                    f"item_{i}": {"url": url, "description": f"URL {i+1}"} 
                    for i, url in enumerate(task.urls)
                }
            }
            
            # Exécuter le pipeline
            pipeline = ScrapingPipeline(use_cache=task.use_cache)
            paths = pipeline.process_urls(urls_config)
            
            # Mettre à jour le statut
            tasks_store[task_id].status = "completed"
            tasks_store[task_id].progress = 1.0
            tasks_store[task_id].details = pipeline.create_result(task_id, paths)
            
        except Exception as e:
            logging.error(f"Erreur lors du traitement de la tâche {task_id}: {str(e)}")
            tasks_store[task_id].status = "error"
            tasks_store[task_id].details = ScrapingResult(
                task_id=task_id,
                status="error",
                errors=[f"Erreur: {str(e)}"]
            )
    
    # Lancer la tâche en arrière-plan
    background_tasks.add_task(process_simple_task)
    
    return tasks_store[task_id]

@router.get("/tasks/{task_id}", response_model=TaskStatus)
async def get_task_status(task_id: str):
    """
    Récupère le statut d'une tâche de scraping
    """
    if task_id not in tasks_store:
        raise HTTPException(status_code=404, detail="Tâche non trouvée")
    
    return tasks_store[task_id]
