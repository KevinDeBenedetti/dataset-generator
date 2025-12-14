import logging
from typing import List, Union

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from server.core.database import get_db
from server.core import Dataset, QASource
from server.services.dataset import (
    get_datasets,
    get_dataset_by_id,
    analyze_dataset_similarities,
    clean_dataset_similarities,
)
from server.schemas.dataset import (
    DatasetResponse,
    SimilarityAnalysisResponse,
    CleanSimilarityResponse,
    DeleteDatasetResponse,
)

router = APIRouter(
    tags=["dataset"],
)


@router.post("/dataset", response_model=DatasetResponse)
async def create_dataset(
    name: str = Query(..., description="Name of the new dataset"),
    description: str = Query(None, description="Optional dataset description"),
    db: Session = Depends(get_db),
):
    """Creates a new dataset"""
    try:
        existing = db.query(Dataset).filter(Dataset.name == name).first()
        if existing:
            raise HTTPException(
                status_code=400, detail=f"Dataset with name '{name}' already exists"
            )

        dataset = Dataset(name=name, description=description)
        db.add(dataset)
        db.commit()
        db.refresh(dataset)

        return {
            "id": dataset.id,
            "name": dataset.name,
            "description": dataset.description,
            "message": "Dataset created successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error creating new dataset: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dataset", response_model=Union[DatasetResponse, List[DatasetResponse]])
async def get_all_datasets(
    dataset_id: str = Query(
        None, description="Optional dataset ID to get specific dataset details"
    ),
    db: Session = Depends(get_db),
):
    """Retrieves all datasets or a specific dataset if ID is provided"""
    try:
        if dataset_id:
            dataset = get_dataset_by_id(db, dataset_id)
            if not dataset:
                raise HTTPException(
                    status_code=404, detail=f"Dataset with ID '{dataset_id}' not found"
                )
            return dataset
        else:
            # Récupérer tous les datasets
            return get_datasets(db)
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error fetching datasets: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/dataset/{dataset_id}/analyze-similarities",
    response_model=SimilarityAnalysisResponse,
)
async def analyze_similarities(
    dataset_id: str,
    threshold: float = Query(0.8, description="Similarity threshold"),
    db: Session = Depends(get_db),
):
    """Analyzes similar questions in a dataset"""
    try:
        return analyze_dataset_similarities(db, dataset_id, threshold)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logging.error(f"Error in analyze_similarities endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/dataset/{dataset_id}/clean-similarities", response_model=CleanSimilarityResponse
)
async def clean_similarities(
    dataset_id: str,
    threshold: float = Query(
        0.8, description="Similarity threshold to detect duplicates (0.0-1.0)"
    ),
    db: Session = Depends(get_db),
):
    """Cleans similar questions in a dataset by removing duplicates"""
    try:
        return clean_dataset_similarities(db, dataset_id, threshold)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logging.error(f"Error in clean_similarities endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/dataset/{dataset_id}", response_model=DeleteDatasetResponse)
async def delete_dataset(dataset_id: str, db: Session = Depends(get_db)):
    """Deletes a dataset and all its associated records"""
    try:
        dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
        if not dataset:
            raise HTTPException(
                status_code=404, detail=f"Dataset with ID '{dataset_id}' not found"
            )

        records_deleted = (
            db.query(QASource).filter(QASource.dataset_id == dataset_id).delete()
        )

        db.delete(dataset)
        db.commit()

        return DeleteDatasetResponse(
            message=f"Dataset '{dataset.name}' deleted successfully",
            dataset_id=dataset_id,
            records_deleted=records_deleted,
        )

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error deleting dataset {dataset_id}: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
