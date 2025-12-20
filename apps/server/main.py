from typing import Any, cast
from contextlib import asynccontextmanager
import logging
import asyncio
from importlib import import_module

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from server.core import logger as logger_module
from server.api import dataset, generate, q_a, openai, owui
from server.services import langfuse
from server.migrations.utils.db_utils import upgrade_db
from server.core.database import SQLALCHEMY_DATABASE_URL

logger_module.setup_logging()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_url = SQLALCHEMY_DATABASE_URL
    try:
        logger.info("Starting migrations...")
        await asyncio.to_thread(upgrade_db, db_url)
        logger.info("Migrations completed")
    except Exception as exc:
        logger.exception("Migration failed: %s", exc)
        raise exc

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

app.include_router(generate.router)
app.include_router(dataset.router)
app.include_router(q_a.router)
app.include_router(openai.router)
app.include_router(owui.owui_router)

if langfuse.is_langfuse_available():
    try:
        langfuse_mod = import_module("server.api.langfuse")
        app.include_router(langfuse_mod.router)
        logging.info("Langfuse routes enabled")
    except Exception as e:
        logging.warning(f"Failed to load Langfuse routes: {e}")
else:
    logging.info("Langfuse not available, skipping Langfuse routes")


@app.get("/")
async def root():
    return RedirectResponse(url="/docs", status_code=302)


@app.get("/health")
async def health():
    return {"status": "ok"}
