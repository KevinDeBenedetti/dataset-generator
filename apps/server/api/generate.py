import logging
import time

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from server.schemas.dataset import TargetLanguage
from server.schemas.generate import (
    DatasetGenerationRequest,
    DatasetGenerationResponse,
    ErrorResponse,
    QAPair,
)
from server.core.database import get_db
from server.pipelines.dataset import DatasetPipeline
from server.core.config import config

router = APIRouter(
    prefix="/dataset",
    tags=["generate"],
)


@router.post(
    "/generate",
    response_model=DatasetGenerationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a dataset from a URL",
    description="Create a new dataset by processing the content of a given URL. "
    "The process includes text cleaning and question-answer generation.",
    responses={
        201: {
            "model": DatasetGenerationResponse,
            "description": "Dataset created successfully",
        },
        400: {
            "model": ErrorResponse,
            "description": "Invalid parameters (model not available, unsupported language, etc.)",
        },
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def create_dataset_for_url(
    request: DatasetGenerationRequest, db: Session = Depends(get_db)
) -> DatasetGenerationResponse:
    """
    Create a new dataset by processing the content of a given URL.

    This endpoint extracts text from the provided URL, cleans it, and generates
    question-answer pairs using the specified language model.
    """
    start_time = time.time()

    try:
        # Apply default values if not provided
        model_cleaning = request.model_cleaning or config.model_cleaning
        target_language = request.target_language or config.target_language
        model_qa = request.model_qa or config.model_qa

        # Validate request parameters
        if model_cleaning not in config.available_models:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Model '{model_cleaning}' not in available models: {config.available_models}",
            )

        if target_language not in [lang.value for lang in TargetLanguage]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid target language: {target_language}. Available options: {[lang.value for lang in TargetLanguage]}",
            )

        if model_qa not in config.available_models:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Model '{model_qa}' not in available models: {config.available_models}",
            )

        target_language_enum = TargetLanguage(target_language)

        pipeline = DatasetPipeline(db)
        result = await pipeline.process_url(
            url=str(request.url),
            dataset_name=request.dataset_name,
            model_cleaning=model_cleaning,
            target_language=target_language_enum,
            model_qa=model_qa,
            similarity_threshold=request.similarity_threshold,
        )

        processing_time = time.time() - start_time

        # Convert QA objects to QAPair objects
        qa_pairs = []
        for qa_item in result.get("qa_pairs", []):
            if hasattr(qa_item, "question") and hasattr(qa_item, "answer"):
                qa_pairs.append(
                    QAPair(question=qa_item.question, answer=qa_item.answer)
                )
            elif isinstance(qa_item, dict):
                qa_pairs.append(
                    QAPair(
                        question=qa_item.get("question", ""),
                        answer=qa_item.get("answer", ""),
                    )
                )

        # Adapt the result to match our response schema
        dataset_id = result.get("dataset_id")

        # Vérification de la présence de l'ID avant de retourner la réponse
        if not dataset_id or not isinstance(dataset_id, str):
            logging.error("Dataset ID is missing in the result")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve dataset ID after generation",
            )

        return DatasetGenerationResponse(
            id=dataset_id,
            qa_pairs=qa_pairs,
            dataset_name=request.dataset_name,
            model_cleaning=model_cleaning,
            target_language=target_language,
            model_qa=model_qa,
            similarity_threshold=request.similarity_threshold,
            total_questions=len(qa_pairs),
            processing_time=processing_time,
        )

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Unexpected error in create_dataset_for_url: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while processing your request.",
        )
