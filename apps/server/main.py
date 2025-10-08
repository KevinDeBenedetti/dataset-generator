from contextlib import asynccontextmanager
import logging
from importlib import import_module

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from core import database, logger
from api import dataset, generate, q_a, openai
from services import langfuse

logger.setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.create_db_and_tables()
    yield


app = FastAPI(
    title="Datasets Generator API",
    description="API to generate datasets from web scraping",
    version="0.0.1",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(generate.router)
app.include_router(dataset.router)
app.include_router(q_a.router)
app.include_router(openai.router)

if langfuse.is_langfuse_available():
    try:
        langfuse_mod = import_module("api.langfuse")
        app.include_router(langfuse_mod.router)
        logging.info("Langfuse routes enabled")
    except Exception as e:
        logging.warning(f"Failed to load Langfuse routes: {e}")
else:
    logging.info("Langfuse not available, skipping Langfuse routes")


@app.get("/")
async def root():
    return RedirectResponse(url="/docs", status_code=302)
