from typing import Any, cast
from contextlib import asynccontextmanager
import logging
import asyncio
import time

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from server.core import logger as logger_module
from server.api import (
    admin,
    agent,
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
from server.services.auth import ensure_secret_is_safe, get_current_user
from server.migrations.utils.db_utils import upgrade_db
from server.core.database import SQLALCHEMY_DATABASE_URL, SessionLocal, database_ready
from server.core.config import config
from server.core.http_security import OriginCheckMiddleware, SecurityHeadersMiddleware
from server.core.log_stream import broadcaster

logger_module.setup_logging()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _seed_dev_users() -> None:
    """Seed the local dev accounts (admin + user). Runs in a worker thread."""
    from server.services.users import seed_dev_users

    db = SessionLocal()
    try:
        created = seed_dev_users(db)
        logger.info("Dev user seeding: %d account(s) created", created)
    finally:
        db.close()


def _purge_expired_refresh_tokens() -> None:
    """Delete revoked/expired refresh token rows. Runs in a worker thread."""
    from server.services.auth import purge_expired_refresh_tokens

    db = SessionLocal()
    try:
        deleted = purge_expired_refresh_tokens(db)
        logger.info("Refresh token purge: %d row(s) deleted", deleted)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_secret_is_safe()
    # Refuse to boot on a configuration unsafe for real users (plain-http
    # cookies, the dev database, one shared secret…). No-op in development.
    config.ensure_production_config()

    # Bind the running loop so log records emitted from worker threads can be
    # delivered to live /debug/logs subscribers.
    broadcaster.bind_loop(asyncio.get_running_loop())

    db_url = SQLALCHEMY_DATABASE_URL
    if config.run_migrations_on_startup:
        try:
            logger.info("Starting migrations...")
            await asyncio.to_thread(upgrade_db, db_url)
            logger.info("Migrations completed")
        except Exception as exc:
            logger.exception("Migration failed: %s", exc)
            raise exc
    else:
        logger.info(
            "Startup migrations skipped (RUN_MIGRATIONS_ON_STARTUP=false): "
            "the schema is migrated by the deployment before the pods start."
        )

    # Optionally seed the local dev accounts (opt-in via SEED_DEV_USERS).
    if config.seed_dev_users:
        try:
            await asyncio.to_thread(_seed_dev_users)
        except Exception:
            logger.exception("Dev user seeding failed")
    else:
        # Without this, an unset SEED_DEV_USERS is completely silent and the only
        # symptom is a 401 on every login — with no hint that no account exists.
        logger.info(
            "Dev user seeding is off (SEED_DEV_USERS unset/false): no local account "
            "is created, so POST /auth/login answers 401 until one exists."
        )

    # Sweep revoked/expired refresh tokens (nothing else ever deletes a row).
    try:
        await asyncio.to_thread(_purge_expired_refresh_tokens)
    except Exception:
        logger.exception("Refresh token purge failed")

    # Single-process local runs: a worker inside the API (deployments run
    # `python -m server.worker` instead).
    worker_stop = asyncio.Event()
    worker_task = None
    if config.embedded_worker:
        from server.services.queue import run_forever

        worker_task = asyncio.create_task(run_forever(worker_stop))
    try:
        yield
    finally:
        if worker_task is not None:
            worker_stop.set()
            await worker_task


def create_app() -> FastAPI:
    """Build the application from the current ``config``.

    A factory (rather than module-level wiring) so tests can build the app under
    different settings — production hardening, docs on/off — from one process.
    """
    docs = config.docs_enabled
    app = FastAPI(
        title="Datasets Generator API",
        description="API to generate datasets from web scraping",
        version="0.0.1",
        lifespan=lifespan,
        # The interactive docs advertise every route to anyone: development only.
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
    )

    # The session is carried by cookies, so CORS is credentialed and must name
    # the allowed origins explicitly: with allow_origins=["*"], Starlette answers
    # a credentialed request by reflecting the caller's origin, which would let
    # any site read authenticated responses. Origins come from CORS_ALLOW_ORIGINS
    # (or FRONTEND_URL); local dev additionally accepts any localhost port. In
    # the single-host production topology the browser never sends a cross-origin
    # request, so this is inert there — but it stays strict, and narrow.
    app.add_middleware(
        cast(Any, CORSMiddleware),
        allow_origins=config.cors_allow_origins,
        allow_origin_regex=config.cors_allow_origin_regex,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )
    logger.info("CORS allowed origins: %s", config.cors_allow_origins or "(none)")

    # CSRF: refuse state-changing requests from a foreign browser origin.
    app.add_middleware(
        cast(Any, OriginCheckMiddleware),
        allowed_origins=config.cors_allow_origins,
        allowed_origin_regex=config.cors_allow_origin_regex,
    )
    app.add_middleware(
        cast(Any, SecurityHeadersMiddleware), hsts=config.auth_cookie_secure
    )

    # Every request, with its outcome — the API had no access log at all
    # (uvicorn's own is not configured), so a 401 from an expired session or a
    # request that never reaches a route handler was invisible in `docker
    # compose logs`. This runs before route-level auth, so it also catches auth
    # failures.
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - started) * 1000
            logger.exception(
                "%s %s -> unhandled exception (%.1fms)",
                request.method,
                request.url.path,
                duration_ms,
            )
            raise
        duration_ms = (time.perf_counter() - started) * 1000
        # The container healthcheck polls /health every few seconds — only log it
        # when it fails, or it drowns everything else.
        if request.url.path in ("/health", "/ready") and response.status_code < 400:
            return response
        logger.info(
            "%s %s -> %d (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response

    # Holds Authlib's OAuth state/nonce between the SSO redirect and its
    # callback. Its own secret and a short life: it only has to outlast a login.
    app.add_middleware(
        cast(Any, SessionMiddleware),
        secret_key=config.effective_session_secret,
        session_cookie=config.session_cookie_name,
        https_only=config.auth_cookie_secure,
        same_site="lax",
        max_age=600,
    )

    # Every feature router requires an authenticated user. Applied at the
    # include level (not on the router objects) so the test app — which mounts
    # the same routers without this dependency — and any future unauthenticated
    # reuse stay unaffected. Public routes: /auth/*, /health, /ready, / and
    # (dev-only) /debug/*.
    auth_required = [Depends(get_current_user)]

    app.include_router(auth.router)
    app.include_router(generate.router, dependencies=auth_required)
    app.include_router(dataset.router, dependencies=auth_required)
    app.include_router(q_a.router, dependencies=auth_required)
    app.include_router(models.router, dependencies=auth_required)
    app.include_router(agent.router, dependencies=auth_required)
    app.include_router(collections.router, dependencies=auth_required)
    app.include_router(quality_rules.router, dependencies=auth_required)
    app.include_router(me.router, dependencies=auth_required)
    app.include_router(admin.router, dependencies=auth_required)
    app.include_router(prompts.router, dependencies=auth_required)
    app.include_router(jobs.router, dependencies=auth_required)

    # The stream is unauthenticated and carries raw log lines, so it only ever
    # exists in an explicitly-declared development environment.
    if config.debug_logs and config.is_development:
        from server.api import debug as debug_api

        app.include_router(debug_api.router)
        logger.info("DEBUG_LOGS enabled — streaming server logs at /debug/logs")
    elif config.debug_logs:
        logger.warning("DEBUG_LOGS ignored: /debug/logs is only mounted in development")

    @app.get("/")
    async def root():
        # Nothing to show at the API root when the docs are off.
        if docs:
            return RedirectResponse(url="/docs", status_code=302)
        return {"status": "ok"}

    @app.get("/health")
    async def health():
        """Liveness: the process answers. Never touches the database."""
        return {"status": "ok"}

    @app.get("/ready")
    async def ready():
        """Readiness: Postgres answers. Failing it takes the pod out of rotation."""
        if await asyncio.to_thread(database_ready):
            return {"status": "ready"}
        return JSONResponse(status_code=503, content={"status": "database unavailable"})

    return app


app = create_app()
