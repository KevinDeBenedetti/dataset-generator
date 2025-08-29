import logging
from fastapi import APIRouter, HTTPException, Body
from typing import Dict, Any, Optional

from app.models.api import TaskStatus
from app.core.config import config
from app.utils import print_summary
from app.pipeline import ScrapingPipeline

router = APIRouter(
    tags=["dataset"],
)

@router.post("/dataset", response_model=TaskStatus)
async def create_dataset(
    urls_config: Optional[Dict[str, Any]] = Body(
        None,
        description="Configuration des URLs à scraper",
        openapi_examples={
            "Example": {
                "summary": "Configuration complète d'exemple",
                "description": "Configuration type basée sur urls.json.example",
                "value": {
                    "official_sources": {
                        "main_site": {
                            "url": "https://example-official.gov",
                            "description": "Main official website of the organization"
                        }
                    }
                }
            }
        }
    )
):
    try:        
        logging.info("Received dataset creation request")
        logging.info(urls_config)
        
        # Pipeline
        pipeline = ScrapingPipeline(use_cache=True)
        
        # Processing
        paths = pipeline.process_urls(urls_config or {})
        
        # Summary
        print_summary(pipeline.metrics, paths)
        
        return TaskStatus(
            task_id="dataset-creation",
            status="completed",
            progress=1.0,
            details=pipeline.create_result("dataset-creation", paths)
        )
    except Exception as e:
        logging.error(f"Error creating dataset: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))