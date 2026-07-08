import logging
from typing import List, Optional
from sqlalchemy.orm import Session
from server.models.dataset import Dataset, QASource


class DatasetService:
    def __init__(self, db: Session):
        self.db = db

    def get_or_create_dataset(
        self,
        name: str,
        description: Optional[str] = None,
        target_language: Optional[str] = None,
    ) -> Dataset:
        """Retrieves an existing dataset or creates a new one"""
        existing_dataset = self.db.query(Dataset).filter(Dataset.name == name).first()

        if existing_dataset:
            logging.info(f"Using existing dataset: {name}")
            # Backfill the language label if it was missing (e.g. older datasets).
            if target_language and not existing_dataset.target_language:
                existing_dataset.target_language = target_language
                self.db.commit()
                self.db.refresh(existing_dataset)
            return existing_dataset

        # Create the dataset automatically
        dataset = Dataset(
            name=name,
            description=description or f"Dataset automatically created for {name}",
            target_language=target_language,
        )
        self.db.add(dataset)
        self.db.commit()
        self.db.refresh(dataset)
        logging.info(f"Created new dataset: {name}")

        return dataset

    def delete_dataset(self, dataset: Dataset) -> None:
        """Deletes a dataset"""
        self.db.delete(dataset)
        self.db.commit()
        logging.info(f"Deleted dataset: {dataset.name}")

    def update_dataset_description(
        self, dataset: Dataset, new_description: str
    ) -> Dataset:
        """Updates the description of a dataset"""
        dataset.description = new_description
        self.db.commit()
        self.db.refresh(dataset)
        logging.info(f"Updated dataset description: {dataset.name}")
        return dataset


def get_qa_records_for_dataset(db: Session, dataset_id: str) -> List[QASource]:
    """All ``QASource`` rows belonging to a dataset.

    Single point of access for the (pipeline sync + Langfuse preview/export)
    call sites that all need "every QA pair currently stored for a dataset" —
    centralizing it means a future move away from querying ``QASource``
    directly is a one-function change instead of three.
    """
    return db.query(QASource).filter(QASource.dataset_id == dataset_id).all()
