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
    Launch a scraping task with hierarchical URL configuration
    similar to the urls.json format
    """
    task_id = str(uuid.uuid4())
    
    # Store the task with initial status
    tasks_store[task_id] = TaskStatus(
        task_id=task_id,
        status="processing",
        progress=0.0
    )
    
    # Define background processing function
    def process_task():
        try:
            # Replace target language if specified
            if task.target_language:
                os.environ["TARGET_LANGUAGE"] = task.target_language
                
            # Execute pipeline
            pipeline = ScrapingPipeline(use_cache=task.use_cache)
            paths = pipeline.process_urls(task.urls_config)
            
            # Update status with result
            tasks_store[task_id].status = "completed"
            tasks_store[task_id].progress = 1.0
            tasks_store[task_id].details = pipeline.create_result(task_id, paths)
            
        except Exception as e:
            logging.error(f"Error processing task {task_id}: {str(e)}")
            tasks_store[task_id].status = "error"
            tasks_store[task_id].details = ScrapingResult(
                task_id=task_id,
                status="error",
                errors=[f"Error: {str(e)}"]
            )
    
    # Launch background task
    background_tasks.add_task(process_task)
    
    return tasks_store[task_id]

@router.post("/simple", response_model=TaskStatus)
async def scrape_simple(task: SimpleUrlList, background_tasks: BackgroundTasks):
    """
    Simplified version for scraping a list of URLs without hierarchical structure
    """
    task_id = str(uuid.uuid4())
    
    # Store the task with initial status
    tasks_store[task_id] = TaskStatus(
        task_id=task_id,
        status="processing",
        progress=0.0
    )
    
    # Function to transform simple list into hierarchical structure
    def process_simple_task():
        try:
            # Convert simple list to hierarchical format
            urls_config = {
                task.category: {
                    f"item_{i}": {"url": url, "description": f"URL {i+1}"} 
                    for i, url in enumerate(task.urls)
                }
            }
            
            # Execute pipeline
            pipeline = ScrapingPipeline(use_cache=task.use_cache)
            paths = pipeline.process_urls(urls_config)
            
            # Update status
            tasks_store[task_id].status = "completed"
            tasks_store[task_id].progress = 1.0
            tasks_store[task_id].details = pipeline.create_result(task_id, paths)
            
        except Exception as e:
            logging.error(f"Error processing task {task_id}: {str(e)}")
            tasks_store[task_id].status = "error"
            tasks_store[task_id].details = ScrapingResult(
                task_id=task_id,
                status="error",
                errors=[f"Error: {str(e)}"]
            )
    
    # Launch background task
    background_tasks.add_task(process_simple_task)
    
    return tasks_store[task_id]

@router.get("/tasks/{task_id}", response_model=TaskStatus)
async def get_task_status(task_id: str):
    """
    Retrieve the status of a scraping task
    """
    if task_id not in tasks_store:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return tasks_store[task_id]
