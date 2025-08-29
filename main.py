from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import dataset
from app.utils import setup_logging

# Base configuration
setup_logging()

# Create FastAPI application
app = FastAPI(
    title="Datasets Generator API",
    description="API to generate datasets from web scraping",
    version="1.0.0"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dataset.router)


# API routes
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
