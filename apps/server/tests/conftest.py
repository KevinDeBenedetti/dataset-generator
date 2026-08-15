"""
Pytest configuration and shared fixtures for FastAPI server tests.
"""

import os

# Set test environment variables BEFORE any imports that load config
os.environ["OPENAI_API_KEY"] = "test-api-key"
os.environ["OPENAI_BASE_URL"] = "https://api.openai.com/v1"
os.environ["OPENAI_LLM_MODEL"] = "gpt-4o-mini"
os.environ["OPENAI_VLM_MODEL"] = "mistral-small-3.1-24b-instruct-2503"
os.environ["OPENAI_EMBEDDING_MODEL"] = "text-embedding-3-small"

import pytest
from typing import Generator
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from server.core.database import Base, get_db, normalize_database_url


@pytest.fixture(scope="session")
def postgres_url() -> Generator[str, None, None]:
    """URL of a throwaway Postgres for the whole test session.

    The app is Postgres-only, so the suite exercises the real dialect rather
    than a stand-in. One container is started per session (spinning one up per
    test would dominate the runtime); isolation comes from ``test_engine``
    creating and dropping the schema around each test.

    Honours ``TEST_DATABASE_URL`` when set, so CI or a developer can point the
    suite at an already-running Postgres and skip the container entirely.
    """
    preset = os.environ.get("TEST_DATABASE_URL")
    if preset:
        yield normalize_database_url(preset)
        return

    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer("postgres:17-alpine", driver="psycopg") as container:
        yield normalize_database_url(container.get_connection_url())


@pytest.fixture(scope="function")
def test_engine(postgres_url: str):
    """Create a test database engine on a clean schema."""
    engine = create_engine(postgres_url)
    # A test that left the schema dirty (or a previous crashed run against a
    # preset TEST_DATABASE_URL) would otherwise fail every later create_all.
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def make_database(postgres_url: str):
    """Factory creating throwaway databases on the session's Postgres server.

    Tests that need two *independent* databases (e.g. proving migrations hit the
    URL they were given and not the one in the environment) used to point at two
    sqlite files; on Postgres the equivalent is two databases on one server.
    Each is dropped when the test ends.
    """
    from sqlalchemy import make_url, text

    base = make_url(postgres_url)
    # CREATE DATABASE cannot run inside a transaction, and cannot run from a
    # connection to the database being dropped — hence AUTOCOMMIT on "postgres".
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    created: list[str] = []

    def _make(name: str) -> str:
        if not name.replace("_", "").isalnum():
            raise ValueError(f"unsafe database name: {name!r}")
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{name}"'))
        created.append(name)
        return base.set(database=name).render_as_string(hide_password=False)

    yield _make

    with admin.connect() as conn:
        for name in created:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


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
    from server.api import (
        auth,
        collections,
        dataset,
        generate,
        q_a,
        openai,
        langfuse,
        prompts,
        quality_rules,
    )

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

    test_app.include_router(auth.router)
    test_app.include_router(generate.router)
    test_app.include_router(dataset.router)
    test_app.include_router(q_a.router)
    test_app.include_router(openai.router)
    test_app.include_router(langfuse.router)
    test_app.include_router(collections.router)
    test_app.include_router(quality_rules.router)
    test_app.include_router(prompts.router)

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

    # The feature routers are mounted here without the app-level auth gate, so
    # these tests exercise handlers directly. The destructive routes still carry
    # a route-level ``Depends(require_admin)``, so satisfy it with a test admin
    # (overriding require_admin also short-circuits its get_current_user
    # sub-dependency — get_current_user itself stays real for the auth tests).
    from server.models.user import User, UserRole
    from server.services.auth import require_admin

    test_app.dependency_overrides[require_admin] = lambda: User(
        id="test-admin", email="admin@test.local", role=UserRole.ADMIN
    )

    with TestClient(test_app) as test_client:
        yield test_client

    test_app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _reset_login_rate_limiter():
    """Clear the process-global login limiter between tests so failed-login
    cases in one test don't throttle another (shared 'testclient' IP)."""
    from server.services.rate_limit import login_rate_limiter

    login_rate_limiter.clear()
    yield
    login_rate_limiter.clear()


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
