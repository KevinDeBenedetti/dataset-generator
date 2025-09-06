import logging
from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Optional, List, Dict, Any
from enum import Enum
from sqlalchemy.orm import Session

from models.dataset import Dataset, QASource
from services.database import get_db
from schemas.q_a import QAListResponse, QAResponse

router = APIRouter(
    prefix="/q_a",
    tags=["q_a"],
)

@router.get("/{dataset_id}", response_model=QAListResponse)
async def get_qa_by_dataset(
    dataset_id: str,
    limit: Optional[int] = Query(None, description="Limit number of results"),
    offset: Optional[int] = Query(0, description="Pagination offset"),
    db: Session = Depends(get_db)
) -> QAListResponse:
    """Retrieve all Q&A items for a specific dataset by its ID"""
    try:
        # Vérifier que le dataset existe
        dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
        if not dataset:
            # build safe list from returned tuples
            available_datasets = [{"id": d[0], "name": d[1]} for d in db.query(Dataset.id, Dataset.name).all()]
            raise HTTPException(
                status_code=404,
                detail=f"Dataset with ID '{dataset_id}' not found. Available datasets: {available_datasets}"
            )
        
        # Construire la requête pour les QA
        query = db.query(QASource).filter(QASource.dataset_id == dataset_id)
        
        # Compter le total
        total_count = query.count()
        
        # Appliquer la pagination
        if offset:
            query = query.offset(offset)
        if limit:
            query = query.limit(limit)
        
        # Récupérer les enregistrements
        qa_records = query.all()
        
        # Formater les données pour la réponse
        qa_data = []
        for record in qa_records:
            qa_data.append({
                "id": record.id,
                "question": record.input.get("question", ""),
                "answer": record.expected_output.get("answer", ""),
                "context": record.input.get("context", ""),
                "source_url": record.input.get("source_url", ""),
                "confidence": record.expected_output.get("confidence", 0.0),
                "created_at": record.created_at,
                "metadata": record.qa_metadata
            })
        
        return {
            "dataset_name": dataset.name,
            "dataset_id": dataset.id,
            "total_count": total_count,
            "returned_count": len(qa_data),
            "offset": offset or 0,
            "limit": limit,
            "qa_data": qa_data
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error fetching Q&A for dataset '{dataset_id}': {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/id/{qa_id}", response_model=QAResponse)
async def get_qa_by_id(
    qa_id: str,
    db: Session = Depends(get_db)
) -> QAResponse:
    """Retrieve a specific Q&A item by its ID"""
    try:
        qa_record = db.query(QASource).filter(QASource.id == qa_id).first()
        
        if not qa_record:
            raise HTTPException(
                status_code=404,
                detail=f"Q&A with ID '{qa_id}' not found"
            )
        
        # Récupérer les informations du dataset associé
        dataset = db.query(Dataset).filter(Dataset.id == qa_record.dataset_id).first()
        
        return {
            "id": qa_record.id,
            "question": qa_record.input.get("question", ""),
            "answer": qa_record.expected_output.get("answer", ""),
            "context": qa_record.input.get("context", ""),
            "source_url": qa_record.input.get("source_url", ""),
            "confidence": qa_record.expected_output.get("confidence", 0.0),
            "created_at": qa_record.created_at,
            "updated_at": qa_record.updated_at,
            "metadata": qa_record.qa_metadata,
            "dataset": {
                "id": dataset.id if dataset else None,
                "name": dataset.name if dataset else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error fetching Q&A '{qa_id}': {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


