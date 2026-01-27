import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from server.models.dataset import QASource


class QAService:
    def __init__(self, db: Session):
        self.db = db

    def add_qa_source(self, qa_source: QASource) -> QASource:
        """Adds a new QASource record to the database"""
        self.db.add(qa_source)
        self.db.commit()
        self.db.refresh(qa_source)
        return qa_source

    def delete_qa_source(self, id: str) -> None:
        """Deletes a QASource record from the database"""
        qa_source = self.db.query(QASource).filter(QASource.id == id).first()
        if qa_source:
            self.db.delete(qa_source)
            self.db.commit()
            logging.info(f"Deleted QASource: {id}")

    def update_qa_source(self, id: str, updates: Dict[str, Any]) -> QASource:
        """Updates a QASource record in the database"""
        qa_source = self.db.query(QASource).filter(QASource.id == id).first()
        if not qa_source:
            raise ValueError(f"QASource with id {id} not found")

        for key, value in updates.items():
            setattr(qa_source, key, value)

        self.db.commit()
        self.db.refresh(qa_source)
        return qa_source

    def get_qa_source(self, id: str) -> QASource:
        """Retrieves a QASource record by ID"""
        qa_source = self.db.query(QASource).filter(QASource.id == id).first()
        if not qa_source:
            raise ValueError(f"QASource with id {id} not found")
        return qa_source

    def process_qa_pairs(
        self,
        qa_list: List[Any],
        cleaned_text: str,
        url: str,
        page_snapshot_id: str,
        dataset_name: str,
        model: str,
        dataset_id: Optional[str] = None,
        similarity_threshold: float = 0.9,
    ) -> Dict[str, int]:
        """Processes and saves QA pairs, checking for duplicates"""
        qa_records = []
        exact_duplicates = 0
        similar_duplicates = 0

        for i, qa_item in enumerate(qa_list):
            duplicate_check = QASource.check_for_duplicates(
                db=self.db,
                question=qa_item.question,
                answer=qa_item.answer,
                context=cleaned_text,
                source_url=url,
                similarity_threshold=similarity_threshold,
            )

            if duplicate_check["type"] == "exact":
                exact_duplicates += 1
                dup_id = duplicate_check.get("duplicate_id")
                dup_id_str = str(dup_id)[:8] if dup_id else "unknown"
                logging.info(f"Exact duplicate found (ID: {dup_id_str}...), skipping")

            elif duplicate_check["type"] == "similar":
                similar_duplicates += 1
                similarity_score = duplicate_check["similarity_score"]
                dup_id = duplicate_check.get("duplicate_id")
                dup_id_str = str(dup_id)[:8] if dup_id else "unknown"
                logging.info(
                    f"Similar question found (similarity: {similarity_score:.2f}, ID: {dup_id_str}...), skipping"
                )

            else:  # new
                qa_record = QASource.from_qa_generation(
                    question=qa_item.question,
                    answer=qa_item.answer,
                    context=cleaned_text,
                    confidence=getattr(qa_item, "confidence", 1.0),
                    source_url=url,
                    page_snapshot_id=page_snapshot_id,
                    dataset_id=dataset_id,  # Passage du dataset_id
                    index=i,
                )

                qa_record.dataset_name = dataset_name
                qa_record.model = model
                qa_records.append(qa_record)
                self.db.add(qa_record)

        self.db.commit()

        logging.info(
            f"Added {len(qa_records)} new QA pairs, "
            f"skipped {exact_duplicates} exact duplicates, "
            f"skipped {similar_duplicates} similar duplicates"
        )

        return {
            "total": len(qa_records),
            "exact_duplicates": exact_duplicates,
            "similar_duplicates": similar_duplicates,
        }
