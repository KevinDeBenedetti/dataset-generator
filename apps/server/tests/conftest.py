"""
Pytest configuration and shared fixtures for FastAPI server tests.
"""

import os

# Set test environment variables BEFORE any imports that load config
os.environ["OPENAI_API_KEY"] = "test-api-key"
os.environ["OPENAI_BASE_URL"] = "https://api.openai.com/v1"
os.environ["AVAILABLE_LLMS"] = (
    "gpt-4o-mini,mistral-small-3.1-24b-instruct-2503,gpt-4-0613,gpt-3.5-turbo-1106"
)
os.environ["DEFAULT_CLEANING_MODEL"] = "gpt-4o-mini"
os.environ["DEFAULT_QA_MODEL"] = "gpt-4o-mini"

from collections.abc import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from server.core.database import Base, get_db

# Use in-memory SQLite for tests
TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="function")
def test_engine():
    """Create a test database engine."""
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def test_db(test_engine) -> Generator[Session, None, None]:
    """Create a test database session."""
    TestingSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=test_engine
    )
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="function")
def client(test_db: Session) -> Generator[TestClient, None, None]:
    """Create a test client with overridden database dependency."""
    from fastapi.middleware.cors import CORSMiddleware

    from server.api import dataset, generate, langfuse, openai, owui, q_a

    # Create test app without lifespan to avoid migration issues
    test_app = FastAPI(
        title="Datasets Generator API",
        description="API to generate datasets from web scraping",
        version="0.0.1",
    )

    test_app.add_middleware(
        CORSMiddleware,  # type: ignore[arg-type]
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    test_app.include_router(generate.router)
    test_app.include_router(dataset.router)
    test_app.include_router(q_a.router)
    test_app.include_router(openai.router)
    test_app.include_router(owui.owui_router)
    test_app.include_router(langfuse.router)

    @test_app.get("/")
    async def root():
        from fastapi.responses import RedirectResponse

        return RedirectResponse(url="/docs", status_code=302)

    @test_app.get("/health")
    async def health():
        return {"status": "ok"}

    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    test_app.dependency_overrides[get_db] = override_get_db

    with TestClient(test_app) as test_client:
        yield test_client

    test_app.dependency_overrides.clear()


@pytest.fixture
def db(test_db: Session) -> Generator[Session, None, None]:
    """Alias for test_db fixture for convenience."""
    yield test_db


@pytest.fixture
def sample_dataset_data():
    """Sample dataset data for tests."""
    return {
        "name": "test_dataset",
        "description": "A test dataset for unit tests",
    }


@pytest.fixture
def sample_qa_data():
    """Sample Q&A data for tests."""
    return {
        "question": "What is the capital of France?",
        "answer": "Paris",
        "context": "France is a country in Europe. Its capital is Paris.",
        "confidence": 0.95,
        "source_url": "https://example.com/france",
    }


@pytest.fixture
def sample_generation_request():
    """Sample dataset generation request for tests."""
    return {
        "url": "https://example.com/document",
        "dataset_name": "generated_dataset",
        "model_cleaning": "mistral-small-3.1-24b-instruct-2503",
        "target_language": "en",
        "model_qa": "mistral-small-3.1-24b-instruct-2503",
        "similarity_threshold": 0.9,
    }
