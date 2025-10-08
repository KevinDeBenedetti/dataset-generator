from datetime import datetime
from fastapi import APIRouter
import httpx
import os
import openai
import instructor
from api.dataset import create_dataset
from models.dataset import QASource
from models.scraper import PageSnapshot
from services.dataset import DatasetService
from services.scraper import ScraperService
from services.qa import QAService
from core.database import get_db
from core.utils.text import chunk_text
from schemas.q_a import UnitQuestionAnswer, UnitQuestionAnswerResponse
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

db = get_db()
client_openai = openai.AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY", "sk-xxxxxx"))
client_instructor = instructor.from_openai(client_openai, mode=instructor.Mode.MD_JSON)

dataset_service = DatasetService(db)
qa_service = QAService(db)
scraper_service = ScraperService(db)


owui_router = APIRouter(tags=["OWUI"])

OWUI_URL = os.getenv("OWUI_URL", "http://localhost:8080")


@owui_router.get("/owui/health")
async def health_check():
    async with httpx.AsyncClient() as client:
        url_health = f"{OWUI_URL}/health"
        response = await client.get(url_health)
        return response.json()


@owui_router.get("/owui/knowledge")
async def get_knowledge():
    async with httpx.AsyncClient() as client:
        url_knowledge = f"{OWUI_URL}/knowledge"
        response = await client.get(url_knowledge)
        return response.json()


@owui_router.get("/owui/knowledge/{knowledge_id}")
async def get_knowledge_by_id(knowledge_id: str):
    async with httpx.AsyncClient() as client:
        url_knowledge = f"{OWUI_URL}/knowledge/{knowledge_id}"
        response = await client.get(url_knowledge)
        return response.json()


@owui_router.get("/owui/files/{id}/data/content")
async def get_file_content(id: str):
    async with httpx.AsyncClient() as client:
        url_file = f"{OWUI_URL}/files/{id}/data/content"
        response = await client.get(url_file)
        return response.json()


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
    knowledge: dict = await get_knowledge_by_id(knowledge_id)
    knowledge_name = knowledge.get("name", f"dataset_{knowledge_id}")
    knowledge_description = knowledge.get("description", "")
    dataset = create_dataset(db, name=knowledge_name, description=knowledge_description)
    dataset_id = dataset.id
    logger.info(
        f"Dataset created with ID: {dataset_id} for knowledge ID: {knowledge_id}"
    )

    files = knowledge.get("files", [])
    if not files:
        return {"error": "No files found for this knowledge ID"}
    file_ids = [file["id"] for file in files]
    file_contents: list[UnitQuestionAnswerResponse] = []
    for file_id in file_ids:
        content: dict = await get_file_content(file_id)
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

    return file_contents
