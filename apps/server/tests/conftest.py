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
# Never download the local embedding model in tests: code paths that use it
# take an injected fake embedder (see tests/services/test_semantic.py).
os.environ["SEMANTIC_ENABLED"] = "false"
# The auth tests exercise the local email/password login and the plain cookie
# names; outside development the app turns the former off and prefixes the
# latter with __Host- (see Config), so pin the test-suite values.
os.environ["ENABLE_LOCAL_LOGIN"] = "true"
# Existing tests drive providers through the env; the per-user paths are tested
# explicitly with their own flags.
os.environ["ALLOW_ENV_CREDENTIALS"] = "true"
os.environ["ENABLE_CLAUDE_PROVIDER"] = "true"
# The Claude provider exists in development and CI only; the suite runs as CI
# (GitHub Actions sets it anyway). Production behaviour is tested explicitly.
os.environ["CI"] = "true"
os.environ["AUTH_COOKIE_NAME"] = "access_token"
os.environ["AUTH_REFRESH_COOKIE_NAME"] = "refresh_token"

import pytest
from contextlib import contextmanager
from typing import Generator
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from server.core.database import Base, get_db, normalize_database_url


@pytest.fixture(autouse=True)
def _no_ambient_database(monkeypatch):
    """Keep tests off the database named in the developer's ``.env``.

    Role model defaults and job runs are read through
    ``server.core.database.get_scoped_db``, whose engine is built from the
    environment at import. A test that doesn't inject a database would silently
    read *that* one — and pass or fail depending on what is stored there (a
    ``claude:`` default set on the Models page, say). Both services degrade to
    their env fallbacks when the database is unreachable, so make it so; tests
    that need a database override this with their own ``get_scoped_db``.
    """
    from contextlib import contextmanager

    @contextmanager
    def unreachable():
        raise RuntimeError("no ambient database in tests")
        yield  # pragma: no cover

    for target in (
        "server.services.model_defaults.get_scoped_db",
        "server.services.jobs.get_scoped_db",
    ):
        monkeypatch.setattr(target, unreachable)


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

    # Explicit credentials: PostgresContainer otherwise reads POSTGRES_USER /
    # POSTGRES_PASSWORD / POSTGRES_DB from the environment, which load_dotenv()
    # fills from the dev .env ("datasets") — a word that also appears in
    # migration messages, breaking the "never logs the password" assertion.
    with PostgresContainer(
        "postgres:17-alpine",
        username="test",
        password="test-only-pw-7f3a",
        dbname="test",
        driver="psycopg",
    ) as container:
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
def datasets_db(monkeypatch, test_engine):
    """Point the dataset service at the per-test database.

    ``services.datasets`` opens its own sessions through ``get_scoped_db``
    (it is called from the pipeline too, outside any request), so overriding
    the ``get_db`` dependency isn't enough to keep it off the developer's real
    database — this rebinds the scoped session itself.
    """
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    @contextmanager
    def scoped():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr("server.services.datasets.get_scoped_db", scoped)
    # Stored secrets and settings live in the same per-test database.
    monkeypatch.setattr("server.services.user_secrets.get_scoped_db", scoped)
    from server.core.config import config as _config
    from server.core.crypto import generate_key

    monkeypatch.setattr(_config, "secrets_encryption_keys_raw", f"t1:{generate_key()}")
    return scoped


def _build_test_app(
    test_db: Session, acting_user=None, real_credentials: bool = False
) -> FastAPI:
    """The API without lifespan or the app-level auth gate.

    With ``acting_user`` the request is authenticated as that (persisted) user:
    both ``get_current_user`` and ``require_admin`` resolve to it, as a valid
    session would. Without it the real ``get_current_user`` stays in place —
    what the auth tests exercise (cookies, refresh, 401s).
    """
    from fastapi.middleware.cors import CORSMiddleware
    from server.api import (
        admin,
        auth,
        collections,
        dataset,
        generate,
        jobs,
        models,
        q_a,
        prompts,
        me,
        quality_rules,
    )
    from server.services.auth import get_current_user, require_admin

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
    test_app.include_router(models.router)
    test_app.include_router(collections.router)
    test_app.include_router(quality_rules.router)
    test_app.include_router(me.router)
    test_app.include_router(admin.router)
    test_app.include_router(prompts.router)
    test_app.include_router(jobs.router)

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

    if not real_credentials:
        # Routes act with a fully-configured set of credentials; the tests that
        # exercise per-user keys ask for the real resolution instead.
        from server.api.deps import get_credentials
        from server.tests.creds import FULL

        test_app.dependency_overrides[get_credentials] = lambda: FULL

    if acting_user is not None:
        test_app.dependency_overrides[get_current_user] = lambda: acting_user
        test_app.dependency_overrides[require_admin] = lambda: acting_user
    else:
        # Auth tests: get_current_user stays real, but the admin-only routes
        # still need a caller that passes their gate.
        from server.models.user import User, UserRole

        test_app.dependency_overrides[require_admin] = lambda: User(
            id="test-admin", email="admin@test.local", role=UserRole.ADMIN
        )
    return test_app


@pytest.fixture(scope="function")
def owner(test_db: Session):
    """The persisted admin the default ``client`` acts as (and owns its data)."""
    from server.models.user import UserRole
    from server.services.users import create_user

    return create_user(
        test_db, email="owner@test.local", password="pw12345", role=UserRole.ADMIN
    )


@pytest.fixture(scope="function")
def client(test_db: Session, datasets_db, owner) -> Generator[TestClient, None, None]:
    """A client authenticated as ``owner`` — feature routes see a signed-in admin."""
    test_app = _build_test_app(test_db, owner)
    with TestClient(test_app) as test_client:
        yield test_client
    test_app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def auth_client(test_db: Session, datasets_db) -> Generator[TestClient, None, None]:
    """A client with the *real* authentication (cookies, refresh, 401s) — for the
    auth tests. Log in through ``/auth/login`` to get a session."""
    test_app = _build_test_app(test_db)
    with TestClient(test_app) as test_client:
        yield test_client
    test_app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def client_for(test_db: Session, datasets_db):
    """Factory: ``client_for(user)`` is a client authenticated as that user.

    For isolation tests, which need two users hitting the same database.
    """
    opened = []

    def make(user, real_credentials: bool = False) -> TestClient:
        test_app = _build_test_app(test_db, user, real_credentials)
        test_client = TestClient(test_app)
        test_client.__enter__()
        opened.append((test_client, test_app))
        return test_client

    yield make
    for test_client, test_app in opened:
        test_client.__exit__(None, None, None)
        test_app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _reset_login_rate_limiter():
    """Clear the process-global limiters between tests so failed-login and
    refresh cases in one test don't throttle another (shared 'testclient' IP)."""
    from server.services import rate_limit

    limiters = (
        rate_limit.login_rate_limiter,
        rate_limit.refresh_rate_limiter,
        rate_limit.sso_rate_limiter,
        rate_limit.secrets_rate_limiter,
    )
    for limiter in limiters:
        limiter.clear()
    yield
    for limiter in limiters:
        limiter.clear()


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
