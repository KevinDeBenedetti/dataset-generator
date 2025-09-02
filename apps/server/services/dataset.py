import logging
from typing import Optional
from sqlalchemy.orm import Session
from models.dataset import Dataset

class DatasetService:
    def __init__(self, db: Session):
        self.db = db
    
    def get_or_create_dataset(self, name: str, description: Optional[str] = None) -> Dataset:
        """Retrieves an existing dataset or creates a new one"""
        existing_dataset = self.db.query(Dataset).filter(Dataset.name == name).first()
        
        if existing_dataset:
            logging.info(f"Using existing dataset: {name}")
            return existing_dataset
        
        # Create the dataset automatically
        dataset = Dataset(
            name=name, 
            description=description or f"Dataset automatically created for {name}"
        )
        self.db.add(dataset)
        self.db.commit()
        self.db.refresh(dataset)
        logging.info(f"Created new dataset: {name}")
        
        return dataset
