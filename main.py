from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import scrape, dataset
from app.utils import setup_logging

# Configuration de base
setup_logging()

# Création de l'application FastAPI
app = FastAPI(
    title="Datasets Generator API",
    description="API pour générer des datasets à partir de scraping web",
    version="1.0.0"
)

# Configuration CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # À adapter selon vos besoins de sécurité
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(scrape.router)
app.include_router(dataset.router)


# Routes API
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
