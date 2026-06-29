import asyncio
import json
import logging
import time
from typing import Any, Dict, Tuple

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from server.schemas.dataset import TargetLanguage
from server.schemas.generate import (
    DatasetGenerationRequest,
    DatasetGenerationResponse,
    ErrorResponse,
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


def _validate_and_resolve(
    request: DatasetGenerationRequest,
) -> Tuple[str, TargetLanguage, str]:
    """Apply defaults and validate model/language. Raises HTTPException(400)."""
    model_cleaning = request.model_cleaning or config.model_cleaning
    target_language = request.target_language or config.target_language
    model_qa = request.model_qa or config.model_qa

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


def _build_response(
    result: Dict[str, Any],
    request: DatasetGenerationRequest,
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
        dataset_name=result.get("dataset_name", request.dataset_name),
        qa_pairs=qa_pairs,
        model_cleaning=model_cleaning,
        target_language=target_language_enum.value,
        model_qa=model_qa,
        similarity_threshold=request.similarity_threshold,
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
            request,
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
                request,
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
