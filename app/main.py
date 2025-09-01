from app.utils.logger import setup_logging

setup_logging()

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging
from importlib import import_module
from fastapi.responses import RedirectResponse

# Import all models to ensure they are registered with SQLAlchemy
from app.models import dataset, scraper

from app.routers import dataset
from app.services.langfuse import is_langfuse_available
from app.services.database import create_db_and_tables

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
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

app.include_router(dataset.router)
from app.routers import generate
app.include_router(generate.router)

if is_langfuse_available():
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


# =================================================================
# TODO : Add more routes
# =================================================================
# - Scraping detail for a specific URL : /scrape/advanced
# =================================================================