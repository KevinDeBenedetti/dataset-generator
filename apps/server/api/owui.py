from datetime import datetime
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse
import httpx
import json
import os
import openai
import instructor
from core import QASource
from models.scraper import PageSnapshot
from services.dataset import DatasetService
from services.scraper import ScraperService
from services.qa import QAService
from core.database import get_db
from core.utils.text import chunk_text
from core.utils.url import clean_base_url, build_api_url
from schemas.q_a import UnitQuestionAnswer, UnitQuestionAnswerResponse
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

db = get_db()
db_session = next(db)
client_openai = openai.AsyncOpenAI(
    api_key=os.getenv("OPENAI_API_KEY", "sk-xxxxxxxxxxxxxxx"),
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
)
client_instructor = instructor.from_openai(client_openai, mode=instructor.Mode.MD_JSON)

dataset_service = DatasetService(db_session)
qa_service = QAService(db_session)
scraper_service = ScraperService(db_session)


owui_router = APIRouter(tags=["OWUI"])


OWUI_URL = clean_base_url(os.getenv("OWUI_URL", "http://localhost:8080/"))
OWUI_TOKEN = os.getenv("OWUI_TOKEN", "sk-xxxxxxxxxxxxxxxx")

headers = {"Authorization": f"Bearer {OWUI_TOKEN}", "Content-Type": "application/json"}


@owui_router.get("/owui/health")
async def health_check():
    try:
        async with httpx.AsyncClient() as client:
            url_health = build_api_url(OWUI_URL, "health")
            response = await client.get(url_health)
            logger.debug(f"Health check response: {response.content}")
            response.raise_for_status()
            return JSONResponse(
                content=response.json(), status_code=response.status_code
            )
    except httpx.HTTPStatusError as e:
        logger.error(f"Health check failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OWUI service is unreachable",
        )


@owui_router.get("/owui/knowledge")
async def get_knowledge():
    try:
        async with httpx.AsyncClient() as client:
            url_knowledge = build_api_url(OWUI_URL, "api/v1/knowledge/")
            response = await client.get(url_knowledge, headers=headers)
            response.raise_for_status()
            return JSONResponse(
                content=response.json(), status_code=response.status_code
            )
    except httpx.HTTPStatusError as e:
        logger.error(f"Failed to fetch knowledge list: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch knowledge list",
        )


@owui_router.get("/owui/knowledge/{knowledge_id}")
async def get_knowledge_by_id(knowledge_id: str):
    try:
        async with httpx.AsyncClient() as client:
            url_knowledge = build_api_url(OWUI_URL, f"api/v1/knowledge/{knowledge_id}")
            response = await client.get(url_knowledge, headers=headers)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error while fetching knowledge {knowledge_id}: {str(e)}")
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Failed to fetch knowledge {knowledge_id}",
        )


@owui_router.get("/owui/files/{id}/data/content")
async def get_file_content(id: str):
    try:
        async with httpx.AsyncClient() as client:
            url_file = build_api_url(OWUI_URL, f"api/v1/files/{id}/data/content")
            response = await client.get(url_file, headers=headers)
            response.raise_for_status()
            return JSONResponse(
                content=response.json(), status_code=response.status_code
            )
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error while fetching file content {id}: {str(e)}")
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Failed to fetch file content {id}",
        )


@owui_router.get(
    "/owui/knowledge/enrichment/{knowledge_id}",
    response_model=list[UnitQuestionAnswerResponse],
)
async def get_knowledge_enrichment(
    knowledge_id: str,
    model: str = "gpt-3.5-turbo",
    chunk_size: int = 5000,
    overlap: int = 200,
):
    try:
        knowledge: dict = await get_knowledge_by_id(knowledge_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch knowledge {knowledge_id}: {str(e)}",
        )

    logger.info(f"Fetched knowledge for ID: {knowledge_id}")
    knowledge_name = knowledge.get("name", f"dataset_{knowledge_id}")
    knowledge_description = knowledge.get("description", "")
    try:
        dataset = dataset_service.get_or_create_dataset(
            name=knowledge_name, description=knowledge_description
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create or retrieve dataset: {str(e)}",
        )
    dataset_id = dataset.id
    logger.info(
        f"Dataset created with ID: {dataset_id} for knowledge ID: {knowledge_id}"
    )

    files = knowledge.get("files", [])
    if not files:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No files found in the specified knowledge",
        )

    file_ids = [file["id"] for file in files]
    file_contents: list[UnitQuestionAnswerResponse] = []
    for file_id in file_ids:
        try:
            content: JSONResponse = await get_file_content(file_id)

            content = json.loads(content.body)
        except Exception as e:
            logger.error(f"Failed to fetch content for file ID {file_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to fetch content for file ID {file_id}: {str(e)}",
            )
        page_snapshot = PageSnapshot(
            url=file_id,
            user_agent="owui-integration",
            content=content.get("content", ""),
            retrieved_at=datetime.now(),
            url_hash=file_id,
            dataset_id=dataset_id,
        )
        scraper_service.add_page_snapshot(page_snapshot)
        logger.info(
            f"PageSnapshot added for file ID: {file_id} in dataset ID: {dataset_id}"
        )
        text = content.get("content", "")
        if not text:
            continue
        chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)
        for chunk in chunks:
            try:
                question_answer_pairs: list[
                    UnitQuestionAnswer
                ] = await client_instructor.chat.completions.create(
                    model=model,
                    response_model=list[UnitQuestionAnswer],
                    messages=[
                        {
                            "role": "user",
                            "content": f"Generate question answer pairs from the following content:\n{chunk}",
                        }
                    ],
                    max_tokens=1500,
                )
                for i, qa in enumerate(question_answer_pairs):
                    file_contents.append(
                        UnitQuestionAnswerResponse(
                            file_id=file_id,
                            dataset_id=dataset_id,
                            question=qa.question,
                            answer=qa.answer,
                            context=qa.context,
                        )
                    )

                    qa_record = QASource.from_qa_generation(
                        question=qa.question,
                        answer=qa.answer,
                        context=qa.context,
                        confidence=qa.confidence,
                        source_url=file_id,
                        page_snapshot_id=page_snapshot.id,
                        dataset_id=dataset_id,  # Passage du dataset_id
                        index=i,
                    )
                    qa_record.dataset_name = knowledge_name
                    qa_record.model = model

                    # Save the QA record to the database or any other storage
                    qa_service.add_qa_source(qa_record)
            except Exception as e:
                logger.error(
                    f"Failed to generate QA pairs for file ID {file_id}: {str(e)}"
                )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to generate QA pairs for file ID {file_id}: {str(e)}",
                )

    return file_contents
