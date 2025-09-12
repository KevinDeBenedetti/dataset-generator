import logging
from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Optional
from sqlalchemy.orm import Session

from models.dataset import Dataset, QASource
from core.database import get_db
from services.langfuse import (
    create_langfuse_dataset_with_items,
    normalize_dataset_name,
)

router = APIRouter(
    prefix="/langfuse",
    tags=["langfuse"],
)


@router.get("/preview")
async def preview_dataset_transformation(
    db: Session = Depends(get_db),
    dataset_name: str = Query(..., description="Dataset name in the database"),
):
    """Preview the dataset transformation for Langfuse without sending it"""
    try:
        dataset = db.query(Dataset).filter(Dataset.name == dataset_name).first()

        if not dataset:
            available_datasets = [
                d.name for d in db.query(Dataset.name).distinct().all()
            ]
            raise HTTPException(
                status_code=404,
                detail=f"Dataset '{dataset_name}' not found. Available datasets: {available_datasets}",
            )

        qa_records = db.query(QASource).filter(QASource.dataset_id == dataset.id).all()

        if not qa_records:
            raise HTTPException(
                status_code=404, detail=f"No QA data found for dataset '{dataset_name}'"
            )

        # Convert directly to Langfuse format
        data_list = [qa.to_langfuse_dataset_item() for qa in qa_records]

        # Return a preview of the first items
        preview_items = data_list[:3]

        return {
            "sample_items": preview_items,
            "total_items": len(data_list),
            "preview_note": f"Showing {len(preview_items)} items out of {len(data_list)} total",
        }

    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Error during preview")
        raise HTTPException(status_code=500, detail=f"Error during preview: {str(e)}")


@router.post("/export")
async def export_dataset(
    db: Session = Depends(get_db),
    dataset_name: str = Query(..., description="Dataset name in the database"),
    langfuse_dataset_name: Optional[str] = Query(
        None, description="Custom name for the dataset in Langfuse"
    ),
):
    """Export a dataset from the database to Langfuse"""
    try:
        # Verify that the dataset exists
        dataset = db.query(Dataset).filter(Dataset.name == dataset_name).first()
        if not dataset:
            available_datasets = [
                d.name for d in db.query(Dataset.name).distinct().all()
            ]
            raise HTTPException(
                status_code=404,
                detail=f"Dataset '{dataset_name}' not found. Available datasets: {available_datasets}",
            )

        # Retrieve QA pairs associated with the dataset
        qa_records = db.query(QASource).filter(QASource.dataset_id == dataset.id).all()

        if not qa_records:
            raise HTTPException(
                status_code=404, detail=f"No QA data found for dataset '{dataset_name}'"
            )

        # Resolve dataset name for Langfuse
        langfuse_name = (
            langfuse_dataset_name
            if langfuse_dataset_name
            else normalize_dataset_name(dataset_name)
        )

        # Convert directly to Langfuse format - no additional transformations needed
        data_list = [qa.to_langfuse_dataset_item() for qa in qa_records]

        # Create the dataset in Langfuse with the data
        dataset_config = {
            "name": langfuse_name,
            "description": f"Dataset {langfuse_name} exporté depuis l'application",
        }
        result = create_langfuse_dataset_with_items(dataset_config, data_list)

        logging.info(
            f"Dataset {dataset_name} successfully exported to Langfuse as {langfuse_name}"
        )

        return {
            "message": "Dataset exported successfully",
            "dataset_name": dataset_name,
            "langfuse_dataset_name": langfuse_name,
            **result,
        }

    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Error exporting to Langfuse")
        raise HTTPException(
            status_code=500, detail=f"Error exporting to Langfuse: {str(e)}"
        )
        logging.exception("Error exporting to Langfuse")
        raise HTTPException(
            status_code=500, detail=f"Error exporting to Langfuse: {str(e)}"
        )
