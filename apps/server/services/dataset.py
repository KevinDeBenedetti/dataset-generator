import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from difflib import SequenceMatcher
from server.models.dataset import Dataset, QASource


class DatasetService:
    def __init__(self, db: Session):
        self.db = db

    def get_or_create_dataset(
        self, name: str, description: Optional[str] = None
    ) -> Dataset:
        """Retrieves an existing dataset or creates a new one"""
        existing_dataset = self.db.query(Dataset).filter(Dataset.name == name).first()

        if existing_dataset:
            logging.info(f"Using existing dataset: {name}")
            return existing_dataset

        # Create the dataset automatically
        dataset = Dataset(
            name=name,
            description=description or f"Dataset automatically created for {name}",
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


def get_datasets(db: Session) -> List[Dict[str, Any]]:
    try:
        datasets = db.query(Dataset).order_by(Dataset.created_at.desc()).all()
        return [
            {"id": dataset.id, "name": dataset.name, "description": dataset.description}
            for dataset in datasets
        ]
    except Exception as e:
        logging.error(f"Erreur lors de la récupération des datasets: {str(e)}")
        raise


def get_dataset_by_id(db: Session, dataset_id: str) -> Dict[str, Any]:
    try:
        dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
        if not dataset:
            return None

        qa_count = db.query(QASource).filter(QASource.dataset_id == dataset_id).count()

        return {
            "id": dataset.id,
            "name": dataset.name,
            "description": dataset.description,
            "created_at": dataset.created_at.isoformat() if dataset.created_at else None,
            "qa_sources_count": qa_count,
        }
    except Exception as e:
        logging.error(
            f"Erreur lors de la récupération du dataset {dataset_id}: {str(e)}"
        )
        raise


def analyze_dataset_similarities(
    db: Session, dataset_id: str, threshold: float = 0.8
) -> Dict[str, Any]:
    """Analyzes similar questions in a dataset"""
    try:
        # Check if dataset exists
        dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
        if not dataset:
            available_datasets = [d.id for d in db.query(Dataset.id).distinct().all()]
            raise ValueError(
                f"Dataset '{dataset_id}' not found. Available datasets: {available_datasets}"
            )

        # Get all records for the dataset
        records = db.query(QASource).filter(QASource.dataset_id == dataset.id).all()

        similarities = []
        processed_pairs = set()

        for i, record1 in enumerate(records):
            for j, record2 in enumerate(records[i + 1 :], i + 1):
                pair_key = tuple(sorted([record1.id, record2.id]))
                if pair_key in processed_pairs:
                    continue

                question1 = record1.input.get("question", "") if record1.input else ""
                question2 = record2.input.get("question", "") if record2.input else ""

                similarity = SequenceMatcher(None, question1, question2).ratio()

                if similarity >= threshold:
                    similarities.append(
                        {
                            "record1_id": record1.id[:8],
                            "record2_id": record2.id[:8],
                            "similarity": round(similarity, 3),
                            "question1": question1[:100] + "..."
                            if len(question1) > 100
                            else question1,
                            "question2": question2[:100] + "..."
                            if len(question2) > 100
                            else question2,
                        }
                    )

                processed_pairs.add(pair_key)

        return {
            "dataset_id": dataset.id,
            "dataset_name": dataset.name,
            "threshold": threshold,
            "total_records": len(records),
            "similar_pairs_found": len(similarities),
            "similarities": sorted(
                similarities, key=lambda x: x["similarity"], reverse=True
            ),
        }

    except Exception as e:
        logging.error(
            f"Error analyzing similarities for dataset {dataset_id}: {str(e)}"
        )
        raise


def clean_dataset_similarities(
    db: Session, dataset_id: str, threshold: float = 0.8
) -> Dict[str, Any]:
    """Cleans similar questions in a dataset by removing duplicates"""
    try:
        # Check if dataset exists
        dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
        if not dataset:
            available_datasets = [d.id for d in db.query(Dataset.id).distinct().all()]
            raise ValueError(
                f"Dataset '{dataset_id}' not found. Available datasets: {available_datasets}"
            )

        # Get all records for the dataset
        records = db.query(QASource).filter(QASource.dataset_id == dataset.id).all()

        if not records:
            raise ValueError(f"No records found for dataset '{dataset_id}'")

        similarities = []
        processed_pairs = set()
        removed_records = []

        for i, record1 in enumerate(records):
            for j, record2 in enumerate(records[i + 1 :], i + 1):
                pair_key = tuple(sorted([record1.id, record2.id]))
                if pair_key in processed_pairs:
                    continue

                question1 = record1.input.get("question", "") if record1.input else ""
                question2 = record2.input.get("question", "") if record2.input else ""

                similarity = SequenceMatcher(None, question1, question2).ratio()

                if similarity >= threshold:
                    # Decide which one to remove
                    confidence1 = (
                        record1.expected_output.get("confidence", 0)
                        if record1.expected_output
                        else 0
                    )
                    confidence2 = (
                        record2.expected_output.get("confidence", 0)
                        if record2.expected_output
                        else 0
                    )

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
                        similarities.append(
                            {
                                "keep_id": record_to_keep.id[:8],
                                "remove_id": record_to_remove.id[:8],
                                "similarity": round(similarity, 3),
                                "keep_question": question1
                                if record_to_keep == record1
                                else question2,
                                "remove_question": question2
                                if record_to_remove == record2
                                else question1,
                            }
                        )

                        removed_records.append(
                            {
                                "id": record_to_remove.id,
                                "question": record_to_remove.input.get("question", "")
                                if record_to_remove.input
                                else "",
                                "similarity": round(similarity, 3),
                                "kept_id": record_to_keep.id[:8],
                            }
                        )

                        # Remove the record
                        db.query(QASource).filter(
                            QASource.id == record_to_remove.id
                        ).delete()

                processed_pairs.add(pair_key)

        # Commit the changes
        db.commit()

        return {
            "dataset_id": dataset.id,
            "dataset_name": dataset.name,
            "threshold": threshold,
            "total_records": len(records),
            "removed_records": len(removed_records),
            "details": sorted(
                similarities, key=lambda x: x["similarity"], reverse=True
            ),
            "removed_items": removed_records,
        }

    except Exception as e:
        db.rollback()
        logging.error(f"Error cleaning similarities for dataset {dataset_id}: {str(e)}")
        raise
