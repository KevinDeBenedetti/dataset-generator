import logging
import json
from pathlib import Path
from fastapi import APIRouter, HTTPException, Body, Query
from typing import List
from langfuse import get_client

from app.utils.langfuse import prepare_langfuse_dataset, load_json_dataset, scan_dataset_files, get_langfuse_client, scan_dataset_files, normalize_dataset_name

router = APIRouter(
    tags=["langfuse"],
)

base = Path(__file__).resolve().parents[2]
qa_dir = base / "datasets" / "qa"

AVAILABLE_DATASETS = scan_dataset_files(qa_dir)
logging.info(f"Available datasets for dropdown: {AVAILABLE_DATASETS}")


@router.post(
    "/langfuse",
    description="Initialize the Langfuse client with environment variables",
)
async def langfuse_endpoint():
    try:
        langfuse = get_langfuse_client()
        return {"message": "Langfuse initialized", "client_repr": str(langfuse)}
    except Exception:
        logging.exception("Error during serialization of the Langfuse client")
        raise HTTPException(status_code=500, detail="Internal error during Langfuse initialization")


@router.get("/langfuse/datasets", response_model=List[str])
async def list_datasets():
    logging.info(f"Base directory: {base}")
    logging.info(f"qa directory: {qa_dir}")

    if not qa_dir.exists() or not qa_dir.is_dir():
        logging.error(f"Directory not found: {qa_dir}")
        raise HTTPException(status_code=404, detail="Directory datasets/qa not found")

    files = scan_dataset_files(qa_dir)
    return files


@router.post("/langfuse/dataset/export")
async def export_dataset(
    filename: str = Query(..., description="Nom du fichier JSON dans datasets/qa", enum=AVAILABLE_DATASETS)
):
    requested = Path(filename).name
    file_path = qa_dir / requested

    if not file_path.exists() or not file_path.is_file():
        logging.error(f"File not found: {file_path}")
        raise HTTPException(status_code=404, detail="File not found in datasets/qa")

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
    

@router.get("/langfuse/dataset/preview")
async def preview_dataset_transformation(
    filename: str = Query(..., description="Name of the JSON file in datasets/qa", enum=AVAILABLE_DATASETS)
):
    """Preview how the data will be transformed for Langfuse without sending it"""
    requested = Path(filename).name
    file_path = qa_dir / requested

    try:
        payload = load_json_dataset(file_path)
        dataset_name = normalize_dataset_name(filename)
        dataset_config, dataset_items = prepare_langfuse_dataset(payload, dataset_name)
        
        preview_items = dataset_items[:3]
        
        return {
            "dataset_config": dataset_config,
            "sample_items": preview_items,
            "total_items": len(dataset_items),
            "preview_note": f"Displaying {len(preview_items)} items out of {len(dataset_items)} total"
        }
        
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Requested file not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logging.exception("Error during preview")
        raise HTTPException(status_code=500, detail=f"Error during preview: {str(e)}")