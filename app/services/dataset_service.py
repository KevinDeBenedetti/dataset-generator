import logging
from typing import List, Dict, Any
from sqlalchemy.orm import Session

from app.models.dataset import Dataset, QASource

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
