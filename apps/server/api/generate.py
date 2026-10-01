import logging
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from server.core.config import config
from server.api.deps import get_credentials
from server.pipelines.dataset import DatasetPipeline
from server.services.credentials import Credentials
from server.schemas.dataset import TargetLanguage
from server.schemas.generate import (
    DatasetGenerationResponse,
    ErrorResponse,
    PipelineStep,
    QAPair,
    UrlGenerationRequest,
)
from server.models.user import User
from server.services.auth import get_current_user
from server.services.model_defaults import resolve_model
from server.services.providers import validate_ref
from server.services.web import WebFetchError

router = APIRouter(
    prefix="/dataset",
    tags=["generate"],
)

_RESPONSES: Dict[int | str, Dict[str, Any]] = {
    201: {"model": DatasetGenerationResponse, "description": "Dataset created"},
    400: {"model": ErrorResponse, "description": "Invalid parameters or source"},
    500: {"model": ErrorResponse, "description": "Internal server error"},
}


def _model(
    role: str, requested: Optional[str], user_id: str, creds: Credentials
) -> str:
    """The request's model reference, else your role default — validated. 400 otherwise."""
    ref = resolve_model(role, requested, user_id=user_id)
    if not ref:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No {role} model configured — pick one on the Models page",
        )
    try:
        return validate_ref(ref, creds)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _language(target_language: Optional[str]) -> TargetLanguage:
    value = target_language or config.target_language
    if value not in [lang.value for lang in TargetLanguage]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid target language: {value}. Available options: "
            f"{[lang.value for lang in TargetLanguage]}",
        )
    return TargetLanguage(value)


def _build_response(
    result: Dict[str, Any],
    dataset_name: str,
    similarity_threshold: float,
    model_cleaning: str,
    target_language_enum: TargetLanguage,
    model_qa: str,
    processing_time: float,
) -> DatasetGenerationResponse:
    """Adapt a pipeline result to the API response. Raises HTTPException(500)."""
    qa_pairs = []
    for qa_item in result.get("qa_pairs", []):
        if hasattr(qa_item, "question") and hasattr(qa_item, "answer"):
            qa_pairs.append(QAPair(question=qa_item.question, answer=qa_item.answer))
        elif isinstance(qa_item, dict):
            qa_pairs.append(
                QAPair(
                    question=qa_item.get("question", ""),
                    answer=qa_item.get("answer", ""),
                )
            )

    dataset_id = result.get("dataset_id")
    if not dataset_id or not isinstance(dataset_id, str):
        logging.error("Dataset ID is missing in the result")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve dataset ID after generation",
        )

    steps = [PipelineStep(**step) for step in result.get("steps", [])]

    return DatasetGenerationResponse(
        id=dataset_id,
        dataset_name=result.get("dataset_name", dataset_name),
        qa_pairs=qa_pairs,
        model_cleaning=model_cleaning,
        target_language=target_language_enum.value,
        model_qa=model_qa,
        similarity_threshold=similarity_threshold,
        total_questions=len(qa_pairs),
        pages_crawled=result.get("pages_crawled", 1),
        processing_time=processing_time,
        steps=steps,
        scraped_content=result.get("scraped_content"),
        persisted=result.get("persisted"),
    )


@router.post(
    "/generate/file",
    response_model=DatasetGenerationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a dataset from an uploaded file (PDF or image)",
    description="Create or extend a dataset from an uploaded PDF or image. Each "
    "page is transcribed with a vision model (the vision role default unless "
    "model_vlm is given), then mined for question-answer pairs.",
    responses=_RESPONSES,
)
async def create_dataset_for_file(
    file: UploadFile = File(..., description="PDF or image file to mine for Q&A"),
    dataset_name: str = Form(...),
    target_language: Optional[str] = Form(None),
    model_qa: Optional[str] = Form(None, description="Model reference for QA"),
    model_vlm: Optional[str] = Form(
        None, description="Model reference for page transcription"
    ),
    similarity_threshold: float = Form(0.85, ge=0.0, le=1.0),
    persist: bool = Form(True),
    user: User = Depends(get_current_user),
    creds: Credentials = Depends(get_credentials),
) -> DatasetGenerationResponse:
    """Create a dataset from an uploaded PDF/image via a vision model."""
    start_time = time.time()
    language = _language(target_language)
    model_qa_r = _model("qa", model_qa, user.id, creds)
    model_vlm_r = _model("vision", model_vlm, user.id, creds)

    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty"
        )

    try:
        result = await DatasetPipeline(user.id, creds).process_file(
            content=content,
            filename=file.filename or "upload",
            content_type=file.content_type or "",
            dataset_name=dataset_name,
            target_language=language,
            model_qa=model_qa_r,
            model_vlm=model_vlm_r,
            similarity_threshold=similarity_threshold,
            persist=persist,
        )
        return _build_response(
            result,
            dataset_name,
            similarity_threshold,
            model_vlm_r,
            language,
            model_qa_r,
            time.time() - start_time,
        )
    except HTTPException:
        raise
    except ValueError as e:
        # Unsupported/corrupt file surfaced by the ingestion layer → 400.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logging.error(f"Unexpected error in create_dataset_for_file: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while processing your request.",
        )


@router.post(
    "/generate/url",
    response_model=DatasetGenerationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a dataset from a web page",
    description="Create or extend a dataset from one web page (no crawling): the "
    "page is fetched, reduced to text, cleaned, then mined for question-answer "
    "pairs. Private/loopback addresses are refused.",
    responses=_RESPONSES,
)
async def create_dataset_for_url(
    request: UrlGenerationRequest,
    user: User = Depends(get_current_user),
    creds: Credentials = Depends(get_credentials),
) -> DatasetGenerationResponse:
    """Create a dataset from a single web page."""
    start_time = time.time()
    language = _language(request.target_language)
    model_cleaning = _model("cleaning", request.model_cleaning, user.id, creds)
    model_qa = _model("qa", request.model_qa, user.id, creds)

    try:
        result = await DatasetPipeline(user.id, creds).process_url(
            url=request.url,
            dataset_name=request.dataset_name,
            target_language=language,
            model_cleaning=model_cleaning,
            model_qa=model_qa,
            similarity_threshold=request.similarity_threshold,
            persist=request.persist,
        )
        return _build_response(
            result,
            request.dataset_name,
            request.similarity_threshold,
            model_cleaning,
            language,
            model_qa,
            time.time() - start_time,
        )
    except WebFetchError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Unexpected error in create_dataset_for_url: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while processing your request.",
        )
