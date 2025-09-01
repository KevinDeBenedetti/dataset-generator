from app.utils.logger import setup_logging

setup_logging()

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging
from typing import List
from importlib import import_module
from fastapi.responses import RedirectResponse

from app.models import dataset
from app.routers import dataset, generate
from app.services import langfuse, database
from app.utils.config import config

@asynccontextmanager
async def lifespan(app: FastAPI):
    database.create_db_and_tables()
    yield

app = FastAPI(
    title="Datasets Generator API",
    description="API to generate datasets from web scraping",
    version="0.0.1",
    lifespan=lifespan
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

if langfuse.is_langfuse_available():
    try:
        langfuse_mod = import_module("app.routers.langfuse")
        app.include_router(langfuse_mod.router)
        logging.info("Langfuse routes enabled")
    except Exception as e:
        logging.exception(f"Failed to enable Langfuse routes: {e}")
else:
    logging.info("Langfuse routes disabled: missing configuration or client unreachable")


@app.get("/")
def read_root():
    return RedirectResponse(url="/docs", status_code=302)

@app.get("/available-models", response_model=List[str], summary="Simple list of available LLM models")
async def get_available_models():
    return config.available_models