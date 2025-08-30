from app.utils.logger import setup_logging

setup_logging()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging
from importlib import import_module

from app.routers import dataset
from app.utils.langfuse import is_langfuse_available


app = FastAPI(
    title="Datasets Generator API",
    description="API to generate datasets from web scraping",
    version="0.0.1"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dataset.router)

# Inclure les routes Langfuse seulement si la configuration + connexion sont OK
if is_langfuse_available():
    try:
        langfuse_mod = import_module("app.routers.langfuse")
        app.include_router(langfuse_mod.router)
        logging.info("Langfuse routes enabled")
    except Exception as e:
        logging.exception(f"Failed to enable Langfuse routes: {e}")
else:
    logging.info("Langfuse routes disabled: missing configuration or client unreachable")

# =================================================================
# TODO : Add more routes
# =================================================================
# - Scraping detail for a specific URL : /scrape/advanced
# - Langfuse export data from a file : /langfuse/export/{file_name}
# =================================================================


@app.get("/")
def read_root():
    return {
        "name": "Datasets Generator API",
        "version": "1.0.0",
        "endpoints": [
            "/scrape/urls", 
            "/scrape/simple",
            "/tasks/{task_id}"
        ]
    }
