import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional

from schemas.dataset import TargetLanguage
from services.database import get_db
from pipelines.dataset import DatasetPipeline
from utils.config import config

router = APIRouter(
    prefix="/generate",
    tags=["generate"],
)

@router.post("/dataset/url")
async def create_dataset_for_url(
    url: str,
    dataset_name: str = Query(..., description="Dataset name (use GET /datasets to see available options)"),
    db: Session = Depends(get_db),
    model_cleaning: Optional[str] = Query(
        default=config.model_cleaning,
        description=f"Model to use for cleaning text (default: {config.model_cleaning})"
    ),
    target_language: Optional[str] = Query(
        default=config.target_language,
        description=f"Target language for QA generation (default: {config.target_language})"
    ),
    model_qa: Optional[str] = Query(
        default=config.model_qa,
        description=f"Model to use for QA generation (default: {config.model_qa})"
    ),
    similarity_threshold: float = Query(
        default=0.9,
        description="Similarity threshold to detect duplicates (0.0-1.0)"
    )
):
    try:
        # Apply default values if not provided
        model_cleaning = model_cleaning or config.model_cleaning
        target_language = target_language or config.target_language
        model_qa = model_qa or config.model_qa
        similarity_threshold = similarity_threshold if similarity_threshold is not None else 0.9

        if model_cleaning not in config.available_models:
            raise HTTPException(
                status_code=400, 
                detail=f"Model '{model_cleaning}' not in available models: {config.available_models}"
            )

        if target_language not in [l.value for l in TargetLanguage]:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid target language: {target_language}. Available options: {[l.value for l in TargetLanguage]}"
            )

        if model_qa not in config.available_models:
            raise HTTPException(
                status_code=400, 
                detail=f"Model '{model_qa}' not in available models: {config.available_models}"
            )

        target_language_enum = TargetLanguage(target_language)
   
        pipeline = DatasetPipeline(db)
        result = await pipeline.process_url(
            url=url,
            dataset_name=dataset_name,
            model_cleaning=model_cleaning,
            target_language=target_language_enum,
            model_qa=model_qa,
            similarity_threshold=similarity_threshold
        )
        
        return result
    
    except Exception as e:
        logging.error(f"Error creating dataset: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
