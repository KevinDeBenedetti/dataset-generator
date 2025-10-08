import uuid
import hashlib
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from sqlalchemy import Column, String, DateTime, JSON, ForeignKey, Boolean
from sqlalchemy.orm import Session, relationship
from difflib import SequenceMatcher

from core.database import Base


class Dataset(Base):
    __tablename__ = "datasets"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relations
    page_snapshots = relationship(
        "PageSnapshot", back_populates="dataset", cascade="all, delete-orphan"
    )


class QASource(Base):
    __tablename__ = "qa_sources"

    id = Column(String, primary_key=True)
    dataset_name = Column(String, index=True)
    dataset_id = Column(String, ForeignKey("datasets.id"), index=True)
    source_trace_id = Column(String)
    page_snapshot_id = Column(String, ForeignKey("page_snapshots.id"))
    input = Column(JSON, nullable=False, default=dict)
    expected_output = Column(JSON, nullable=False, default=dict)
    qa_metadata = Column(JSON, nullable=False, default=dict)
    status = Column(String, default="ACTIVE", index=True)
    model = Column(String)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    human_reviewed = Column(Boolean, default=False)

    @staticmethod
    def compute_hash_from_content(
        question: str, answer: str, context: str, source_url: str = ""
    ) -> str:
        question_normalized = " ".join(question.strip().split())
        context_normalized = " ".join(context.strip().split())

        content = f"{question_normalized}|{context_normalized}|{source_url}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @classmethod
    def is_duplicate_by_similarity(
        cls,
        db: Session,
        question: str,
        context: str,
        source_url: str,
        threshold: float = 0.9,
    ) -> Optional[str]:
        # Retrieve all records and filter in Python
        # This avoids issues with the .astext operator in some SQLAlchemy versions
        all_records = db.query(cls).all()

        # Manually filter records with the same source URL
        similar_records = []
        for record in all_records:
            record_source_url = record.input.get("source_url", "")
            if record_source_url == source_url:
                similar_records.append(record)

        # Check question similarity
        for record in similar_records:
            existing_question = record.input.get("question", "")
            existing_context = record.input.get("context", "")

            # Calculate question similarity
            question_similarity = SequenceMatcher(
                None, question, existing_question
            ).ratio()

            # Optional: also check context similarity
            context_similarity = SequenceMatcher(
                None, context, existing_context
            ).ratio()

            # If the question is very similar AND the context is identical or very similar
            if question_similarity >= threshold and context_similarity >= 0.95:
                return record.id

        return None

    @classmethod
    def check_for_duplicates(
        cls,
        db: Session,
        question: str,
        answer: str,
        context: str,
        source_url: str,
        similarity_threshold: float = 0.9,
    ) -> Dict[str, Optional[str]]:
        """Checks for duplicates by exact hash AND similarity"""

        # 1. Check by exact hash
        exact_hash = cls.compute_hash_from_content(
            question, answer, context, source_url
        )
        exact_duplicate = db.query(cls).filter(cls.id == exact_hash).first()

        if exact_duplicate:
            return {
                "type": "exact",
                "duplicate_id": exact_duplicate.id,
                "similarity_score": 1.0,
            }

        # 2. Check by similarity
        similar_id = cls.is_duplicate_by_similarity(
            db, question, context, source_url, similarity_threshold
        )

        if similar_id:
            # Calculate similarity score for information
            similar_record = db.query(cls).filter(cls.id == similar_id).first()
            existing_question = similar_record.input.get("question", "")
            similarity_score = SequenceMatcher(
                None, question, existing_question
            ).ratio()

            return {
                "type": "similar",
                "duplicate_id": similar_id,
                "similarity_score": similarity_score,
            }

        return {"type": "new", "duplicate_id": None, "similarity_score": 0.0}

    @classmethod
    def from_qa_generation(
        cls,
        question: str,
        answer: str,
        context: str,
        confidence: float = 1.0,
        source_url: str = "",
        source_trace_id: Optional[str] = None,
        page_snapshot_id: Optional[str] = None,
        dataset_id: Optional[str] = None,  # Ajout du paramètre dataset_id
        index: int = 0,
    ) -> "QASource":
        if not question or not answer:
            raise ValueError("Question and answer are required")

        # Generate ID based on content
        qa_id = cls.compute_hash_from_content(question, answer, context, source_url)

        return cls(
            id=qa_id,
            input={
                "question": question,
                "context": context,
                "source_url": source_url,
                "index": index,
            },
            expected_output={"answer": answer, "confidence": float(confidence)},
            source_trace_id=source_trace_id,
            page_snapshot_id=page_snapshot_id,
            dataset_id=dataset_id,  # Utilisation du dataset_id
            qa_metadata={
                "generation_timestamp": datetime.now(timezone.utc).isoformat(),
                "context_length": len(context) if context else 0,
                "question_length": len(question),
                "answer_length": len(answer),
                "content_hash": qa_id,
            },
        )

    def to_langfuse_dataset_item(self) -> Dict[str, Any]:
        """Convert to Langfuse Dataset Item format"""
        item = {"input": self.input, "id": self.id}

        if self.expected_output:
            item["expected_output"] = self.expected_output

        if self.qa_metadata:
            item["metadata"] = self.qa_metadata

        return item
