import logging
from fastapi import APIRouter, HTTPException, Body
from typing import Dict, Any, Optional

from app.models.dataset import DatasetResult

from app.core.config import config
from app.utils import print_summary
from app.pipeline import ScrapingPipeline

router = APIRouter(
    tags=["dataset"],
)

@router.post("/dataset", response_model=DatasetResult)
async def create_dataset(
    urls_config: Optional[Dict[str, Any]] = Body(
        None,
        description="Configuration for URLs to scrape",
        openapi_examples={
            "Example": {
                "summary": "Full example configuration",
                "description": "Typical configuration based on urls.json.example",
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

        print_summary(pipeline.metrics, paths)

        # Convert paths to strings to satisfy Pydantic validation
        files = [str(p) for p in paths] if paths else []

        return DatasetResult(
            task_id="dataset-creation",
            status="completed",
            urls_processed=pipeline.metrics.urls_processed,
            qa_pairs_generated=pipeline.metrics.qa_pairs_generated,
            files_generated=files,
            errors=pipeline.metrics.errors,
            duration=pipeline.metrics.duration,
            rate=pipeline.metrics.rate
        )
        
    except Exception as e:
        logging.error(f"Error creating dataset: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))