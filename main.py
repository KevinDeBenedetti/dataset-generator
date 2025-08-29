from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import scrape, dataset
from app.utils import setup_logging

# Basic configuration
setup_logging()

# Create FastAPI application
app = FastAPI(
    title="Datasets Generator API",
    description="API for generating datasets from web scraping",
    version="1.0.0"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adapt according to your security needs
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(scrape.router)
app.include_router(dataset.router)


# API Routes
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
