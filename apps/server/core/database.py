import os
from sqlalchemy import create_engine, make_url
from sqlalchemy.engine import URL
from sqlalchemy.orm import scoped_session, sessionmaker, declarative_base
from contextlib import contextmanager

from dotenv import load_dotenv

# Alembic imports this module directly (migrations/env.py), so it cannot rely on
# core.config having loaded .env first. load_dotenv does not override variables
# already set, so compose's explicit DATABASE_URL still wins.
load_dotenv()


def _env(name: str, default: str) -> str:
    """Read an env var, treating a present-but-blank value as unset.

    `.env.example` ships `DATABASE_URL=` blank so the compose service is used by
    default, and `make env` copies it verbatim — so blank has to mean "absent".
    """
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def default_database_url() -> str:
    """The compose Postgres as seen *from the host*.

    Used when DATABASE_URL is unset, so `make dev-local` (uvicorn outside
    Docker) and a bare `alembic` invocation both reach the running stack. Built
    from the same POSTGRES_* variables that seed the container, so changing the
    credentials in .env keeps this in sync. Inside compose the server is handed
    an explicit DATABASE_URL pointing at postgres:5432 instead.
    """
    user = _env("POSTGRES_USER", "datasets")
    password = _env("POSTGRES_PASSWORD", "datasets")
    database = _env("POSTGRES_DB", "datasets")
    port = _env("POSTGRES_HOST_PORT", "5452")
    return f"postgresql+psycopg://{user}:{password}@localhost:{port}/{database}"


def normalize_database_url(url: str) -> str:
    """Force the psycopg (v3) driver and reject non-Postgres URLs.

    psycopg2 is not installed, so a bare ``postgresql://`` — the form managed
    providers and ``postgres://`` connection strings hand out — would fail at
    import time with a ModuleNotFoundError that says nothing about the real
    problem. Rewriting the driver here means any accepted spelling of a
    Postgres URL works.
    """
    parsed: URL = make_url(url)
    backend = parsed.get_backend_name()
    if backend not in ("postgresql", "postgres"):
        raise ValueError(
            f"DATABASE_URL must be a PostgreSQL URL, got {backend!r} "
            f"(this app no longer supports any other database)."
        )
    return parsed.set(drivername="postgresql+psycopg").render_as_string(
        hide_password=False
    )


SQLALCHEMY_DATABASE_URL = normalize_database_url(
    _env("DATABASE_URL", "") or default_database_url()
)

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    # Postgres (and anything in front of it) drops idle connections; without a
    # liveness check the first query after an idle period fails instead of
    # transparently getting a fresh connection.
    pool_pre_ping=True,
    pool_recycle=1800,
)

SessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=engine, expire_on_commit=False
)
Base = declarative_base()
Session = scoped_session(SessionLocal)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_scoped_db():
    db = Session()
    try:
        yield db
    finally:
        db.close()


def create_db_and_tables():
    try:
        Base.metadata.create_all(bind=engine)
    except Exception:
        raise
