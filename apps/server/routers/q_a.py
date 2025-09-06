import logging
from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Optional, List, Dict, Any
from enum import Enum
from sqlalchemy.orm import Session

from models.dataset import Dataset, QASource
from services.database import get_db

router = APIRouter(
    prefix="/q_a",
    tags=["q_a"],
)

@router.get("/{dataset_id}")
async def get_qa_by_dataset(
    dataset_id: str,
    limit: Optional[int] = Query(None, description="Limite le nombre de résultats"),
    offset: Optional[int] = Query(0, description="Décalage pour la pagination"),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Récupère toutes les questions-réponses d'un dataset spécifique par son ID"""
    try:
        # Vérifier que le dataset existe
        dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
        if not dataset:
            available_datasets = [{"id": d.id, "name": d.name} for d in db.query(Dataset.id, Dataset.name).all()]
            raise HTTPException(
                status_code=404,
                detail=f"Dataset avec l'ID '{dataset_id}' introuvable. Datasets disponibles: {available_datasets}"
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
        logging.error(f"Erreur lors de la récupération des Q&A pour le dataset '{dataset_id}': {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/id/{qa_id}")
async def get_qa_by_id(
    qa_id: str,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Récupère une question-réponse spécifique par son ID"""
    try:
        qa_record = db.query(QASource).filter(QASource.id == qa_id).first()
        
        if not qa_record:
            raise HTTPException(
                status_code=404,
                detail=f"Question-réponse avec l'ID '{qa_id}' introuvable"
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
        logging.error(f"Erreur lors de la récupération de la Q&A '{qa_id}': {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


