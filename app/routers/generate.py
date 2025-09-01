import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.utils.common import print_summary, qa_to_dict_list, flatten_urls, is_valid_url
from app.schemas.dataset import TargetLanguage, ModelName
from app.services.database import get_db
from app.pipelines.dataset import DatasetPipeline

router = APIRouter(
    prefix="/generate",
    tags=["generate"],
)

@router.post("/dataset/url")
async def create_dataset_for_url(
    url: str,
    dataset_name: str = Query(..., description="Dataset name (use GET /datasets to see available options)"),
    db: Session = Depends(get_db),
    model_cleaning: ModelName = Query(),
    target_language: TargetLanguage = Query(),
    model_qa: ModelName = Query(),
    similarity_threshold: float = Query(0.9, description="Similarity threshold to detect duplicates (0.0-1.0)")
):
    try:
        # Use the pipeline to process the URL
        pipeline = DatasetPipeline(db)
        result = await pipeline.process_url(
            url=url,
            dataset_name=dataset_name,
            model_cleaning=model_cleaning,
            target_language=target_language,
            model_qa=model_qa,
            similarity_threshold=similarity_threshold
        )
        
        return result
    
    except Exception as e:
        logging.error(f"Error creating dataset: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


