from typing import Any, cast
from contextlib import asynccontextmanager
import logging
import asyncio
from importlib import import_module

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from server.core import logger as logger_module
from server.api import agent, auth, collections, dataset, generate, q_a, openai
from server.services import langfuse
from server.services.auth import get_current_user
from server.migrations.utils.db_utils import upgrade_db
from server.core.database import SQLALCHEMY_DATABASE_URL, SessionLocal
from server.core.config import config
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Bind the running loop so log records emitted from worker threads can be
    # delivered to live /debug/logs subscribers.
    broadcaster.bind_loop(asyncio.get_running_loop())

    db_url = SQLALCHEMY_DATABASE_URL
    try:
        logger.info("Starting migrations...")
        await asyncio.to_thread(upgrade_db, db_url)
        logger.info("Migrations completed")
    except Exception as exc:
        logger.exception("Migration failed: %s", exc)
        raise exc

    # Optionally seed the local dev accounts (opt-in via SEED_DEV_USERS).
    if config.seed_dev_users:
        try:
            await asyncio.to_thread(_seed_dev_users)
        except Exception:
            logger.exception("Dev user seeding failed")

    yield


app = FastAPI(
    title="Datasets Generator API",
    description="API to generate datasets from web scraping",
    version="0.0.1",
    lifespan=lifespan,
)

app.add_middleware(
    cast(Any, CORSMiddleware),
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Required by Authlib's OIDC client to hold the OAuth state/nonce between the
# /auth/oidc/login redirect and the /auth/oidc/callback.
app.add_middleware(
    cast(Any, SessionMiddleware),
    secret_key=config.auth_secret_key,
    https_only=config.auth_cookie_secure,
    same_site="lax",
)

# Every feature router requires an authenticated user. Applied at the
# include level (not on the router objects) so the test app — which mounts the
# same routers without this dependency — and any future unauthenticated reuse
# stay unaffected. Public routes: /auth/*, /health, / and (dev-only) /debug/*.
auth_required = [Depends(get_current_user)]

app.include_router(auth.router)
app.include_router(generate.router, dependencies=auth_required)
app.include_router(dataset.router, dependencies=auth_required)
app.include_router(q_a.router, dependencies=auth_required)
app.include_router(openai.router, dependencies=auth_required)
app.include_router(agent.router, dependencies=auth_required)
app.include_router(collections.router, dependencies=auth_required)

if config.debug_logs:
    from server.api import debug as debug_api

    app.include_router(debug_api.router)
    logger.info("DEBUG_LOGS enabled — streaming server logs at /debug/logs")

# Always mount the Langfuse routes: each endpoint guards itself with a clear
# 503 when Langfuse isn't configured/reachable. Mounting them conditionally on
# startup availability meant a missing/invalid config produced a confusing 404
# and required a server restart once the config was fixed.
try:
    langfuse_mod = import_module("server.api.langfuse")
    app.include_router(langfuse_mod.router, dependencies=auth_required)
    if langfuse.is_langfuse_available():
        logging.info("Langfuse routes enabled (Langfuse reachable)")
    else:
        logging.info(
            "Langfuse routes enabled, but Langfuse is not configured/reachable; "
            "endpoints will return 503 until LANGFUSE_* env vars are set."
        )
except Exception as e:
    logging.warning(f"Failed to load Langfuse routes: {e}")


@app.get("/")
async def root():
    return RedirectResponse(url="/docs", status_code=302)


@app.get("/health")
async def health():
    return {"status": "ok"}
