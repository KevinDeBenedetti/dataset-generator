import logging
from difflib import SequenceMatcher
from typing import List
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from models.dataset import Dataset, QASource
from services.database import get_db
from services.dataset_service import get_dataset_names, get_datasets, get_dataset_by_id

router = APIRouter(
    prefix="/dataset",
    tags=["dataset"],
)

def get_dataset_enum(db: Session):
    """Crée une énumération dynamique des noms de datasets disponibles"""
    datasets = db.query(Dataset.name).distinct().all()
    dataset_names = [d.name for d in datasets]
    
    if not dataset_names:
        return type('DatasetEnum', (str, Enum), {'__empty__': 'Aucun dataset disponible'})
    
    enum_dict = {name.replace('-', '_').replace(' ', '_'): name for name in dataset_names}
    return type('DatasetEnum', (str, Enum), enum_dict)

@router.post("")
async def create_dataset(
    name: str = Query(..., description="Name of the new dataset"),
    description: str = Query(None, description="Optional dataset description"),
    db: Session = Depends(get_db)
):
    """Creates a new dataset"""
    try:
        # Check that the name doesn't already exist
        existing = db.query(Dataset).filter(Dataset.name == name).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"Dataset with name '{name}' already exists")
        
        dataset = Dataset(name=name, description=description)
        db.add(dataset)
        db.commit()
        db.refresh(dataset)
        
        return {"id": dataset.id, "name": dataset.name, "description": dataset.description, "message": "Dataset created successfully"}
    
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error creating new dataset: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("")
async def get_all_datasets(
    dataset_id: str = Query(None, description="Optional dataset ID to get specific dataset details"),
    db: Session = Depends(get_db)
):
    """Retrieves all datasets or a specific dataset if ID is provided"""
    try:
        if dataset_id:
            # Récupérer un dataset spécifique
            dataset = get_dataset_by_id(db, dataset_id)
            if not dataset:
                raise HTTPException(status_code=404, detail=f"Dataset with ID '{dataset_id}' not found")
            return dataset
        else:
            # Récupérer tous les datasets
            return get_datasets(db)
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error fetching datasets: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{dataset_name}/analyze-similarities")
async def analyze_similarities(
    dataset_name: str,
    threshold: float = Query(0.8, description="Similarity threshold"),
    db: Session = Depends(get_db)
):
    """Analyzes similar questions in a dataset"""
    # Vérifier que le dataset existe
    dataset = db.query(Dataset).filter(Dataset.name == dataset_name).first()
    if not dataset:
        available_datasets = [d.name for d in db.query(Dataset.name).distinct().all()]
        raise HTTPException(
            status_code=404,
            detail=f"Dataset '{dataset_name}' introuvable. Datasets disponibles: {available_datasets}"
        )
    
    records = db.query(QASource).filter(QASource.dataset_id == dataset.id).all()
    
    similarities = []
    processed_pairs = set()
    
    for i, record1 in enumerate(records):
        for j, record2 in enumerate(records[i+1:], i+1):
            pair_key = tuple(sorted([record1.id, record2.id]))
            if pair_key in processed_pairs:
                continue
            
            question1 = record1.input.get('question', '')
            question2 = record2.input.get('question', '')
            
            similarity = SequenceMatcher(None, question1, question2).ratio()
            
            if similarity >= threshold:
                similarities.append({
                    "record1_id": record1.id[:8],
                    "record2_id": record2.id[:8],
                    "similarity": round(similarity, 3),
                    "question1": question1[:100] + "..." if len(question1) > 100 else question1,
                    "question2": question2[:100] + "..." if len(question2) > 100 else question2
                })
            
            processed_pairs.add(pair_key)
    
    return {
        "dataset": dataset_name,
        "threshold": threshold,
        "total_records": len(records),
        "similar_pairs_found": len(similarities),
        "similarities": sorted(similarities, key=lambda x: x["similarity"], reverse=True)
    }

@router.post("/{dataset_name}/clean-similarities")
async def clean_similarities(
    dataset_name: str,
    threshold: float = Query(0.8, description="Similarity threshold to detect duplicates (0.0-1.0)"),
    db: Session = Depends(get_db)
):
    """Cleans similar questions in a dataset by removing duplicates"""
    # Vérifier que le dataset existe
    dataset = db.query(Dataset).filter(Dataset.name == dataset_name).first()
    if not dataset:
        available_datasets = [d.name for d in db.query(Dataset.name).distinct().all()]
        raise HTTPException(
            status_code=404,
            detail=f"Dataset '{dataset_name}' introuvable. Datasets disponibles: {available_datasets}"
        )
    
    records = db.query(QASource).filter(QASource.dataset_id == dataset.id).all()
    
    if not records:
        raise HTTPException(status_code=404, detail=f"No records found for dataset '{dataset_name}'")
    
    similarities = []
    processed_pairs = set()
    removed_records = []
    
    for i, record1 in enumerate(records):
        for j, record2 in enumerate(records[i+1:], i+1):
            pair_key = tuple(sorted([record1.id, record2.id]))
            if pair_key in processed_pairs:
                continue
            
            question1 = record1.input.get('question', '')
            question2 = record2.input.get('question', '')
            
            similarity = SequenceMatcher(None, question1, question2).ratio()
            
            if similarity >= threshold:
                # Decide which one to remove
                confidence1 = record1.expected_output.get('confidence', 0) if record1.expected_output else 0
                confidence2 = record2.expected_output.get('confidence', 0) if record2.expected_output else 0
                
                if confidence1 > confidence2:
                    record_to_keep = record1
                    record_to_remove = record2
                elif confidence2 > confidence1:
                    record_to_keep = record2
                    record_to_remove = record1
                else:
                    # If confidences are equal, keep the oldest
                    if record1.created_at < record2.created_at:
                        record_to_keep = record1
                        record_to_remove = record2
                    else:
                        record_to_keep = record2
                        record_to_remove = record1
                
                # Check if this record hasn't already been marked for removal
                if record_to_remove.id not in [r["id"] for r in removed_records]:
                    similarities.append({
                        "keep_id": record_to_keep.id[:8],
                        "remove_id": record_to_remove.id[:8],
                        "similarity": round(similarity, 3),
                        "keep_question": question1 if record_to_keep == record1 else question2,
                        "remove_question": question2 if record_to_remove == record2 else question1
                    })
                    
                    removed_records.append({
                        "id": record_to_remove.id,
                        "question": record_to_remove.input.get('question', '') if record_to_remove.input else '',
                        "similarity": round(similarity, 3),
                        "kept_id": record_to_keep.id[:8]
                    })
                    
                    # Remove the record
                    db.query(QASource).filter(QASource.id == record_to_remove.id).delete()
            
            processed_pairs.add(pair_key)
    
    # Validate the changes
    db.commit()
    
    return {
        "dataset": dataset_name,
        "threshold": threshold,
        "total_records": len(records),
        "removed_records": len(removed_records),
        "details": sorted(similarities, key=lambda x: x["similarity"], reverse=True),
        "removed_items": removed_records
    }

@router.delete("/{dataset_id}")
async def delete_dataset(
    dataset_id: str,
    db: Session = Depends(get_db)
):
    """Deletes a dataset and all its associated records"""
    try:
        dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
        if not dataset:
            raise HTTPException(status_code=404, detail=f"Dataset with ID '{dataset_id}' not found")
        
        records_deleted = db.query(QASource).filter(QASource.dataset_id == dataset_id).delete()
        
        db.delete(dataset)
        db.commit()
        
        return {
            "message": f"Dataset '{dataset.name}' deleted successfully",
            "dataset_id": dataset_id,
            "records_deleted": records_deleted
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error deleting dataset {dataset_id}: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
        raise
    except Exception as e:
        logging.error(f"Error deleting dataset {dataset_id}: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
