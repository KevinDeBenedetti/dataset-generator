import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from server.schemas.dataset import TargetLanguage
from server.schemas.generate import (
    DatasetGenerationRequest,
    DatasetGenerationResponse,
    ErrorResponse,
    GitHubGenerationRequest,
    PipelineStep,
    QAPair,
)
from server.core.database import get_db
from server.pipelines.dataset import DatasetPipeline
from server.core.config import config

router = APIRouter(
    prefix="/dataset",
    tags=["generate"],
)


def _resolve_models(
    model_cleaning: Optional[str],
    target_language: Optional[str],
    model_qa: Optional[str],
) -> Tuple[str, TargetLanguage, str]:
    """Apply defaults and validate model/language. Raises HTTPException(400)."""
    model_cleaning = model_cleaning or config.model_cleaning
    target_language = target_language or config.target_language
    model_qa = model_qa or config.model_qa

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

    return model_cleaning, TargetLanguage(target_language), model_qa


def _validate_and_resolve(
    request: DatasetGenerationRequest,
) -> Tuple[str, TargetLanguage, str]:
    """Resolve/validate models for a URL generation request."""
    return _resolve_models(
        request.model_cleaning, request.target_language, request.model_qa
    )


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
        langfuse=result.get("langfuse"),
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
        model_cleaning, target_language_enum, model_qa = _validate_and_resolve(request)

        pipeline = DatasetPipeline(db)
        result = await pipeline.process_url(
            url=str(request.url),
            dataset_name=request.dataset_name,
            model_cleaning=model_cleaning,
            target_language=target_language_enum,
            model_qa=model_qa,
            similarity_threshold=request.similarity_threshold,
            crawl=request.crawl,
            max_depth=request.max_depth,
            max_pages=request.max_pages,
            crawl_delay_seconds=request.crawl_delay_seconds,
            max_pages_per_domain=request.max_pages_per_domain,
            sync_langfuse=request.sync_langfuse,
        )

        processing_time = time.time() - start_time
        return _build_response(
            result,
            request.dataset_name,
            request.similarity_threshold,
            model_cleaning,
            target_language_enum,
            model_qa,
            processing_time,
        )

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Unexpected error in create_dataset_for_url: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while processing your request.",
        )


def _resolve_file_models(
    model_qa: Optional[str],
    target_language: Optional[str],
    model_vlm: Optional[str],
) -> Tuple[str, TargetLanguage, str]:
    """Validate/resolve the QA model, language and vision model for a file upload.

    Raises HTTPException(400) on an unavailable model / unsupported language, or
    when no vision model is configured (the file path needs one to read pages).
    """
    model_qa = model_qa or config.model_qa
    target_language = target_language or config.target_language
    model_vlm = model_vlm or config.openai_vlm_model

    if model_qa not in config.available_models:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Model '{model_qa}' not in available models: {config.available_models}",
        )
    if target_language not in [lang.value for lang in TargetLanguage]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid target language: {target_language}. Available options: {[lang.value for lang in TargetLanguage]}",
        )
    if not model_vlm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No vision model configured (set OPENAI_VLM_MODEL) — required to read uploaded files.",
        )
    if model_vlm not in config.available_models:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Vision model '{model_vlm}' not in available models: {config.available_models}",
        )
    return model_qa, TargetLanguage(target_language), model_vlm


@router.post(
    "/generate/file",
    response_model=DatasetGenerationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a dataset from an uploaded file (PDF or image)",
    description="Create a new dataset from an uploaded PDF or image. Each page is "
    "transcribed with the configured vision model (OPENAI_VLM_MODEL), then mined "
    "for question-answer pairs.",
    responses={
        201: {
            "model": DatasetGenerationResponse,
            "description": "Dataset created successfully",
        },
        400: {
            "model": ErrorResponse,
            "description": "Invalid parameters or unsupported/corrupt file",
        },
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def create_dataset_for_file(
    file: UploadFile = File(..., description="PDF or image file to mine for Q&A"),
    dataset_name: str = Form(...),
    target_language: Optional[str] = Form(None),
    model_qa: Optional[str] = Form(None),
    model_vlm: Optional[str] = Form(None),
    similarity_threshold: float = Form(0.9, ge=0.0, le=1.0),
    sync_langfuse: bool = Form(True),
    db: Session = Depends(get_db),
) -> DatasetGenerationResponse:
    """Create a dataset from an uploaded PDF/image via the vision model."""
    start_time = time.time()

    model_qa_r, target_language_enum, model_vlm_r = _resolve_file_models(
        model_qa, target_language, model_vlm
    )

    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty"
        )

    try:
        pipeline = DatasetPipeline(db)
        result = await pipeline.process_file(
            content=content,
            filename=file.filename or "upload",
            content_type=file.content_type or "",
            dataset_name=dataset_name,
            target_language=target_language_enum,
            model_qa=model_qa_r,
            model_vlm=model_vlm_r,
            similarity_threshold=similarity_threshold,
            sync_langfuse=sync_langfuse,
        )

        processing_time = time.time() - start_time
        return _build_response(
            result,
            dataset_name,
            similarity_threshold,
            model_vlm_r,
            target_language_enum,
            model_qa_r,
            processing_time,
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
    "/generate/github",
    response_model=DatasetGenerationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a dataset from a GitHub account's public docs",
    description="Create a new dataset from a GitHub account: each public repo's "
    "README and top-level docs are cleaned and mined for question-answer pairs. "
    "An optional token only raises the API rate limit (public data only).",
    responses={
        201: {
            "model": DatasetGenerationResponse,
            "description": "Dataset created successfully",
        },
        400: {
            "model": ErrorResponse,
            "description": "Invalid parameters or unknown GitHub user",
        },
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def create_dataset_for_github(
    request: GitHubGenerationRequest, db: Session = Depends(get_db)
) -> DatasetGenerationResponse:
    """Create a dataset from a GitHub account's public README/docs."""
    start_time = time.time()

    model_cleaning, target_language_enum, model_qa = _resolve_models(
        request.model_cleaning, request.target_language, request.model_qa
    )

    try:
        pipeline = DatasetPipeline(db)
        result = await pipeline.process_github(
            username=request.github_username,
            token=request.github_token,
            dataset_name=request.dataset_name,
            model_cleaning=model_cleaning,
            target_language=target_language_enum,
            model_qa=model_qa,
            max_repos=request.max_repos,
            similarity_threshold=request.similarity_threshold,
            sync_langfuse=request.sync_langfuse,
        )

        processing_time = time.time() - start_time
        return _build_response(
            result,
            request.dataset_name,
            request.similarity_threshold,
            model_cleaning,
            target_language_enum,
            model_qa,
            processing_time,
        )

    except HTTPException:
        raise
    except ValueError as e:
        # Unknown user / rate-limited / bad input surfaced by the GitHub layer.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logging.error(f"Unexpected error in create_dataset_for_github: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while processing your request.",
        )


@router.post(
    "/generate/stream",
    summary="Generate a dataset from a URL (streaming progress)",
    description="Same as POST /dataset/generate, but streams pipeline progress "
    "as Server-Sent Events: a `step` event per pipeline stage, a `page` event "
    "per crawled page, then a final `result` (or `error`) event.",
)
async def stream_dataset_for_url(
    request: DatasetGenerationRequest, db: Session = Depends(get_db)
) -> StreamingResponse:
    """Stream the generation pipeline's progress to the client over SSE.

    Each event is a JSON object with a ``type`` field: ``step`` (a pipeline
    stage finished), ``page`` (a page was crawled), ``result`` (the final
    response payload) or ``error``.
    """
    # Validate up front so bad input returns a normal 400 (not a streamed error).
    model_cleaning, target_language_enum, model_qa = _validate_and_resolve(request)

    queue: asyncio.Queue = asyncio.Queue()
    start_time = time.time()

    def on_progress(event: Dict[str, Any]) -> None:
        # Called synchronously from the pipeline (same event loop) — safe.
        queue.put_nowait(event)

    pipeline = DatasetPipeline(db)

    async def run() -> None:
        try:
            result = await pipeline.process_url(
                url=str(request.url),
                dataset_name=request.dataset_name,
                model_cleaning=model_cleaning,
                target_language=target_language_enum,
                model_qa=model_qa,
                similarity_threshold=request.similarity_threshold,
                crawl=request.crawl,
                max_depth=request.max_depth,
                max_pages=request.max_pages,
                crawl_delay_seconds=request.crawl_delay_seconds,
                max_pages_per_domain=request.max_pages_per_domain,
                sync_langfuse=request.sync_langfuse,
                on_progress=on_progress,
            )
            processing_time = time.time() - start_time
            response = _build_response(
                result,
                request.dataset_name,
                request.similarity_threshold,
                model_cleaning,
                target_language_enum,
                model_qa,
                processing_time,
            )
            queue.put_nowait(
                {"type": "result", "data": response.model_dump(mode="json")}
            )
        except HTTPException as e:
            queue.put_nowait({"type": "error", "detail": e.detail})
        except Exception as e:
            logging.error(f"Unexpected error in stream_dataset_for_url: {str(e)}")
            queue.put_nowait(
                {
                    "type": "error",
                    "detail": "An unexpected error occurred while processing your request.",
                }
            )
        finally:
            queue.put_nowait(None)  # sentinel: stream complete

    task = asyncio.create_task(run())

    async def event_generator():
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
