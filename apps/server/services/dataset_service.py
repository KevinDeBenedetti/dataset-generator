import logging
from typing import List, Dict, Any
from sqlalchemy.orm import Session

from models.dataset import Dataset, QASource

def get_dataset_names(db: Session) -> List[str]:
    """Récupère la liste des noms de datasets depuis la base de données"""
    try:
        datasets = db.query(Dataset).all()
        return [dataset.name for dataset in datasets]
    except Exception as e:
        logging.error(f"Erreur lors de la récupération des noms de datasets: {str(e)}")
        return []

def get_datasets(db: Session) -> List[Dict[str, Any]]:
    """Récupère la liste complète des datasets disponibles"""
    try:
        datasets = db.query(Dataset).order_by(Dataset.created_at.desc()).all()
        return [{"id": dataset.id, "name": dataset.name, "description": dataset.description} for dataset in datasets]
    except Exception as e:
        logging.error(f"Erreur lors de la récupération des datasets: {str(e)}")
        raise

def get_dataset_by_id(db: Session, dataset_id: str) -> Dict[str, Any]:
    """Récupère un dataset spécifique par son ID avec ses détails"""
    try:
        dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
        if not dataset:
            return None
        
        # Compter le nombre de QASource associées
        qa_count = db.query(QASource).filter(QASource.dataset_id == dataset_id).count()
        
        return {
            "id": dataset.id,
            "name": dataset.name,
            "description": dataset.description,
            "created_at": dataset.created_at,
            "qa_sources_count": qa_count
        }
    except Exception as e:
        logging.error(f"Erreur lors de la récupération du dataset {dataset_id}: {str(e)}")
        raise
