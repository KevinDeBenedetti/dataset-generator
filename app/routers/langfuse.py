import logging
import json
from pathlib import Path
from fastapi import APIRouter, HTTPException, Body, Query
from typing import List
from langfuse import get_client

router = APIRouter(
    tags=["langfuse"],
)

# Scanner une fois au démarrage pour fournir les options d'énumération (affichées en dropdown dans Swagger)
base = Path(__file__).resolve().parents[2]  # /.../mi/datasets
qa_dir = base / "datasets" / "qa"
def _scan_datasets():
    if qa_dir.exists() and qa_dir.is_dir():
        return sorted([p.name for p in qa_dir.glob("*.json") if p.is_file()])
    return []

AVAILABLE_DATASETS = _scan_datasets()
logging.info(f"Available datasets for dropdown: {AVAILABLE_DATASETS}")

@router.post("/langfuse")
async def langfuse_endpoint():
    langfuse = get_client()
    logging.info("Langfuse client initialized")
    logging.info(f"Langfuse client: {langfuse}")
    try:
        # Ne pas renvoyer l'objet client non sérialisable directement
        return {"message": "Langfuse initialisé", "client_repr": str(langfuse)}
    except Exception:
        logging.exception("Erreur lors de la sérialisation du client Langfuse")
        raise HTTPException(status_code=500, detail="Erreur interne lors de l'initialisation de Langfuse")

# Nouvelle route : lister les fichiers JSON disponibles dans datasets/qa
@router.get("/langfuse/datasets", response_model=List[str])
async def list_datasets():
    base = Path(__file__).resolve().parents[2]  # /.../mi/datasets
    logging.info(f"Base directory: {base}")
    qa_dir = base / "datasets" / "qa"
    logging.info(f"qa directory: {qa_dir}")
    if not qa_dir.exists() or not qa_dir.is_dir():
        logging.error(f"Répertoire introuvable: {qa_dir}")
        raise HTTPException(status_code=404, detail="Répertoire datasets/qa introuvable")
    files = sorted([p.name for p in qa_dir.glob("*.json") if p.is_file()])
    return files

# Modifier la route d'export pour utiliser un Query param avec enum (affichera une liste déroulante)
@router.post("/langfuse/dataset/export")
async def export_dataset(filename: str = Query(..., description="Nom du fichier JSON dans datasets/qa", enum=AVAILABLE_DATASETS)):
    requested = Path(filename).name
    file_path = qa_dir / requested

    if not file_path.exists() or not file_path.is_file():
        logging.error(f"Fichier introuvable: {file_path}")
        raise HTTPException(status_code=404, detail="Fichier demandé introuvable dans datasets/qa")

    try:
        with file_path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        logging.exception("Erreur lors de la lecture du fichier JSON")
        raise HTTPException(status_code=500, detail="Impossible de lire le fichier JSON demandé")

    langfuse = get_client()
    logging.info("Langfuse client initialized for dataset export")
    try:
        logging.info(f"Pret à envoyer {file_path} vers Langfuse (taille: {len(json.dumps(payload))} octets)")
        return {"message": "Dataset exporté avec succès (simulation)", "filename": requested}
    except Exception:
        logging.exception("Erreur lors de l'exportation du dataset Langfuse")
        raise HTTPException(status_code=500, detail="Erreur interne lors de l'exportation du dataset Langfuse")