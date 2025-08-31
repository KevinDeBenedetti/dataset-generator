import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException, Body, Query
from typing import List, Optional
from langfuse import get_client

from app.utils.langfuse import (
    prepare_langfuse_dataset,
    load_json_dataset,
    scan_dataset_files,
    get_langfuse_client,
    normalize_dataset_name,
    create_langfuse_dataset_with_items,
)

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
    filename: str = Query(..., description="Name of the JSON file in datasets/qa", enum=AVAILABLE_DATASETS),
    dataset_name: Optional[str] = Query(None, description="Custom name for the dataset in Langfuse")
):
    requested = Path(filename).name
    file_path = qa_dir / requested

    try:
        # Load file data
        payload = load_json_dataset(file_path)

        # Resolve dataset name: use provided param or derive from filename.
        dataset_name_used = dataset_name if dataset_name else normalize_dataset_name(requested)

        # Determine the actual list of items from the payload.
        if isinstance(payload, list):
            data_list = payload
        elif isinstance(payload, dict) and isinstance(payload.get("items"), list):
            data_list = payload["items"]
        elif isinstance(payload, dict) and "question" in payload and "answer" in payload:
            # single-object QA -> wrap into a list
            data_list = [payload]
        else:
            raise ValueError("JSON dataset must be a list of items, a dict with an 'items' list, or a single QA object")

        dataset_config, dataset_items = prepare_langfuse_dataset(data_list, dataset_name_used)

        result = create_langfuse_dataset_with_items(dataset_config, dataset_items)

        logging.info(f"Dataset {dataset_name_used} successfully exported to Langfuse")

        return {
            "message": "Dataset exported successfully",
            "filename": requested,
            **result
        }
    
    except FileNotFoundError:
        logging.error(f"File not found: {file_path}")
        raise HTTPException(status_code=404, detail="Requested file not found in datasets/qa")
    except ValueError as e:
        logging.error(f"Data error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logging.exception("Error during export to Langfuse")
        raise HTTPException(
            status_code=500,
            detail=f"Error during export to Langfuse: {str(e)}"
        )
    

@router.get("/langfuse/dataset/preview")
async def preview_dataset_transformation(
    filename: str = Query(..., description="Name of the JSON file in datasets/qa", enum=AVAILABLE_DATASETS)
):
    """Preview how the data will be transformed for Langfuse without sending it"""
    requested = Path(filename).name
    file_path = qa_dir / requested

    try:
        payload = load_json_dataset(file_path)
        # use the actual filename (requested) to derive a default dataset name for preview
        dataset_name = normalize_dataset_name(requested)
        # Determine list of items like in export to avoid same class-of-type errors
        if isinstance(payload, list):
            data_list = payload
        elif isinstance(payload, dict) and isinstance(payload.get("items"), list):
            data_list = payload["items"]
        elif isinstance(payload, dict) and "question" in payload and "answer" in payload:
            data_list = [payload]
        else:
            raise ValueError("JSON dataset must be a list of items, a dict with an 'items' list, or a single QA object")

        dataset_config, dataset_items = prepare_langfuse_dataset(data_list, dataset_name)
         
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