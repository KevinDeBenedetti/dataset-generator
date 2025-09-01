import logging
from typing import Optional
from sqlalchemy.orm import Session
from app.models.dataset import Dataset

class DatasetService:
    def __init__(self, db: Session):
        self.db = db
    
    def get_or_create_dataset(self, name: str, description: Optional[str] = None) -> Dataset:
        """Récupère un dataset existant ou en crée un nouveau"""
        existing_dataset = self.db.query(Dataset).filter(Dataset.name == name).first()
        
        if existing_dataset:
            logging.info(f"Using existing dataset: {name}")
            return existing_dataset
        
        # Créer le dataset automatiquement
        dataset = Dataset(
            name=name, 
            description=description or f"Dataset créé automatiquement pour {name}"
        )
        self.db.add(dataset)
        self.db.commit()
        self.db.refresh(dataset)
        logging.info(f"Created new dataset: {name}")
        
        return dataset
