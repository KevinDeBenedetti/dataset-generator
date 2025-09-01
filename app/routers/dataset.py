import logging
from difflib import SequenceMatcher

from fastapi import Depends

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List
from sqlalchemy.orm import Session

from app.models.dataset import Dataset, QASource

router = APIRouter(
    prefix="/dataset",
    tags=["dataset"],
)

from app.services.database import get_db

def get_dataset_names(db: Session) -> List[str]:
    """Récupère la liste des noms de datasets pour la validation"""
    try:
        datasets = db.query(Dataset).all()
        return [dataset.name for dataset in datasets]
    except Exception:
        return []

@router.post("")
async def create_dataset(
    name: str = Query(..., description="Nom du nouveau dataset"),
    description: str = Query(None, description="Description optionnelle du dataset"),
    db: Session = Depends(get_db)
):
    """Crée un nouveau dataset"""
    try:
        # Vérifier que le nom n'existe pas déjà
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

@router.get("/datasets")
async def get_datasets(db: Session = Depends(get_db)):
    """Récupère la liste de tous les datasets disponibles"""
    try:
        datasets = db.query(Dataset).order_by(Dataset.created_at.desc()).all()
        return [{"id": dataset.id, "name": dataset.name, "description": dataset.description} for dataset in datasets]
    except Exception as e:
        logging.error(f"Error fetching datasets: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{dataset_name}/analyze-similarities")
async def analyze_similarities(
    dataset_name: str,
    threshold: float = Query(0.8, description="Seuil de similarité"),
    db: Session = Depends(get_db)
):
    """Analyse les questions similaires dans un dataset"""
    records = db.query(QASource).filter(QASource.dataset_name == dataset_name).all()
    
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
    threshold: float = Query(0.8, description="Seuil de similarité pour détecter les doublons (0.0-1.0)"),
    db: Session = Depends(get_db)
):
    """Nettoie les questions similaires dans un dataset en supprimant les doublons"""
    records = db.query(QASource).filter(QASource.dataset_name == dataset_name).all()
    
    if not records:
        raise HTTPException(status_code=404, detail=f"Aucun enregistrement trouvé pour le dataset '{dataset_name}'")
    
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
                # Décider lequel supprimer
                confidence1 = record1.expected_output.get('confidence', 0) if record1.expected_output else 0
                confidence2 = record2.expected_output.get('confidence', 0) if record2.expected_output else 0
                
                if confidence1 > confidence2:
                    record_to_keep = record1
                    record_to_remove = record2
                elif confidence2 > confidence1:
                    record_to_keep = record2
                    record_to_remove = record1
                else:
                    # Si confiances égales, garder le plus ancien
                    if record1.created_at < record2.created_at:
                        record_to_keep = record1
                        record_to_remove = record2
                    else:
                        record_to_keep = record2
                        record_to_remove = record1
                
                # Vérifier si ce record n'a pas déjà été marqué pour suppression
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
                    
                    # Supprimer l'enregistrement
                    db.query(QASource).filter(QASource.id == record_to_remove.id).delete()
            
            processed_pairs.add(pair_key)
    
    # Valider les changements
    db.commit()
    
    return {
        "dataset": dataset_name,
        "threshold": threshold,
        "total_records": len(records),
        "removed_records": len(removed_records),
        "details": sorted(similarities, key=lambda x: x["similarity"], reverse=True),
        "removed_items": removed_records
    }