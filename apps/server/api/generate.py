import logging
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from starlette.concurrency import run_in_threadpool

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
from server.services.model_defaults import get_default_model
from server.services.providers import validate_ref
from server.services.web import WebFetchError

from server.schemas.recipes import HF_REPO_PATTERN
from server.services.drafts import create_generation_draft
from server.services.huggingface import HuggingFaceNotConfiguredError

router = APIRouter(
    prefix="/dataset",
    tags=["generate"],
)

_RESPONSES: Dict[int | str, Dict[str, Any]] = {
    201: {"model": DatasetGenerationResponse, "description": "Dataset created"},
    400: {"model": ErrorResponse, "description": "Invalid parameters or source"},
    500: {"model": ErrorResponse, "description": "Internal server error"},
}


def _model(user_id: str, creds: Credentials, requested: Optional[str]) -> str:
    """The request's model reference, else your LLM — validated; 400 otherwise.

    Reads your saved model (a database session): call it once per request,
    through ``run_in_threadpool`` from the async routes.
    """
    ref = requested or get_default_model(user_id)
    if not ref:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No LLM configured — set OPENAI_LLM_MODEL, or pick one on the "
            "Models page",
        )
    try:
        return validate_ref(ref, creds)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


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
    model: str,
    target_language_enum: TargetLanguage,
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
        model=model,
        target_language=target_language_enum.value,
        similarity_threshold=similarity_threshold,
        total_questions=len(qa_pairs),
        pages_crawled=result.get("pages_crawled", 1),
        processing_time=processing_time,
        steps=steps,
        scraped_content=result.get("scraped_content"),
        persisted=result.get("persisted"),
    )


async def _keep_draft(
    user: User,
    creds: Credentials,
    target_repo: str,
    result: Dict[str, Any],
    *,
    title: str,
    source: str,
    kind: str,
    language: TargetLanguage,
    model_ref: str,
) -> Optional[str]:
    """Keep the generation as a draft to review (services/drafts.py); None
    when it produced no pair."""
    items = result.get("items") or []
    if not items:
        return None
    try:
        return await run_in_threadpool(
            create_generation_draft,
            user.id,
            creds,
            target_repo,
            items,
            title=title,
            source=source,
            kind=kind,
            language=language.value,
            model_ref=model_ref,
        )
    except HuggingFaceNotConfiguredError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)
        ) from e


@router.post(
    "/generate/file",
    response_model=DatasetGenerationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a dataset from an uploaded file (PDF or image)",
    description="Create or extend a dataset from an uploaded PDF or image. Each "
    "page is transcribed by your LLM (it must read images), then mined for "
    "question-answer pairs.",
    responses=_RESPONSES,
)
async def create_dataset_for_file(
    file: UploadFile = File(..., description="PDF or image file to mine for Q&A"),
    dataset_name: str = Form(..., min_length=1, max_length=100),
    target_language: Optional[str] = Form(None),
    model: Optional[str] = Form(
        None, max_length=200, description="Model reference (default: your LLM)"
    ),
    similarity_threshold: float = Form(0.85, ge=0.0, le=1.0),
    persist: bool = Form(True),
    target_repo: Optional[str] = Form(
        None,
        max_length=193,
        pattern=HF_REPO_PATTERN,
        description="Hugging Face dataset to publish to: the pairs become a draft",
    ),
    user: User = Depends(get_current_user),
    creds: Credentials = Depends(get_credentials),
) -> DatasetGenerationResponse:
    """Create a dataset from an uploaded PDF/image, read by your LLM."""
    start_time = time.time()
    language = _language(target_language)
    model_ref = await run_in_threadpool(_model, user.id, creds, model)

    # Refuse an oversized upload before holding it in memory: the size the
    # multipart parser saw first, then a bounded read in case it reported none.
    too_large = HTTPException(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        detail=f"The file is larger than {config.max_upload_bytes // (1024 * 1024)} MB",
    )
    if file.size is not None and file.size > config.max_upload_bytes:
        raise too_large
    content = await file.read(config.max_upload_bytes + 1)
    if len(content) > config.max_upload_bytes:
        raise too_large
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
            model=model_ref,
            similarity_threshold=similarity_threshold,
            # A draft replaces the local dataset.
            persist=persist and not target_repo,
        )
        response = _build_response(
            result,
            dataset_name,
            similarity_threshold,
            model_ref,
            language,
            time.time() - start_time,
        )
        if target_repo:
            response.draft_run_id = await _keep_draft(
                user,
                creds,
                target_repo,
                result,
                title=dataset_name,
                source=f"file://{file.filename or 'upload'}",
                kind="file",
                language=language,
                model_ref=model_ref,
            )
        return response
    except HTTPException:
        raise
    except ValueError as e:
        # Unsupported/corrupt file surfaced by the ingestion layer → 400.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e
    except Exception as e:
        logging.error(f"Unexpected error in create_dataset_for_file: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while processing your request.",
        ) from e


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
    model_ref = await run_in_threadpool(_model, user.id, creds, request.model)

    try:
        result = await DatasetPipeline(user.id, creds).process_url(
            url=request.url,
            dataset_name=request.dataset_name,
            target_language=language,
            model=model_ref,
            similarity_threshold=request.similarity_threshold,
            # A draft replaces the local dataset.
            persist=request.persist and not request.target_repo,
        )
        response = _build_response(
            result,
            request.dataset_name,
            request.similarity_threshold,
            model_ref,
            language,
            time.time() - start_time,
        )
        if request.target_repo:
            response.draft_run_id = await _keep_draft(
                user,
                creds,
                request.target_repo,
                result,
                title=request.dataset_name,
                source=request.url,
                kind="web",
                language=language,
                model_ref=model_ref,
            )
        return response
    except WebFetchError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Unexpected error in create_dataset_for_url: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while processing your request.",
        ) from e
