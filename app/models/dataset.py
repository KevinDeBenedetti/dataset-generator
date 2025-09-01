import uuid
import hashlib
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from sqlalchemy import Column, String, DateTime, JSON, ForeignKey
from sqlalchemy.orm import Session
from difflib import SequenceMatcher

from app.services.database import Base

class Dataset(Base):
    __tablename__ = "datasets"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class QASource(Base):
    __tablename__ = "qa_sources"

    id = Column(String, primary_key=True)  # Supprime le default
    dataset_name = Column(String, index=True)
    dataset_run_id = Column(String, index=True)
    source_trace_id = Column(String)
    page_snapshot_id = Column(String, ForeignKey("page_snapshots.id"))
    input = Column(JSON, nullable=False, default=dict)
    expected_output = Column(JSON, nullable=False, default=dict)
    qa_metadata = Column(JSON, nullable=False, default=dict)
    status = Column(String, default="ACTIVE", index=True)
    model = Column(String)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    @staticmethod
    def compute_hash_from_content(question: str, answer: str, context: str, source_url: str = "") -> str:
        question_normalized = ' '.join(question.strip().split())
        # answer_normalized = ' '.join(answer.strip().split())
        context_normalized = ' '.join(context.strip().split())

        # content = f"{question_normalized}|{answer_normalized}|{context_normalized}|{source_url}"
        content = f"{question_normalized}|{context_normalized}|{source_url}"
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    @classmethod
    def is_duplicate_by_similarity(
        cls,
        db: Session,
        question: str,
        context: str,
        source_url: str,
        threshold: float = 0.9
    ) -> Optional[str]:
        # Récupérer tous les enregistrements et filtrer en Python
        # Cela évite les problèmes avec l'opérateur .astext dans certaines versions de SQLAlchemy
        all_records = db.query(cls).all()
        
        # Filtrer manuellement les enregistrements avec la même URL source
        similar_records = []
        for record in all_records:
            record_source_url = record.input.get('source_url', '')
            if record_source_url == source_url:
                similar_records.append(record)

        # Vérifier la similarité des questions
        for record in similar_records:
            existing_question = record.input.get('question', '')
            existing_context = record.input.get('context', '')
            
            # Calculer la similarité de la question
            question_similarity = SequenceMatcher(None, question, existing_question).ratio()
            
            # Optionnel : vérifier aussi la similarité du contexte
            context_similarity = SequenceMatcher(None, context, existing_context).ratio()
            
            # Si la question est très similaire ET le contexte est identique ou très similaire
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
        similarity_threshold: float = 0.9
    ) -> Dict[str, Optional[str]]:
        """Vérifie les doublons par hash exact ET par similarité"""
        
        # 1. Vérification par hash exact
        exact_hash = cls.compute_hash_from_content(question, answer, context, source_url)
        exact_duplicate = db.query(cls).filter(cls.id == exact_hash).first()
        
        if exact_duplicate:
            return {
                "type": "exact",
                "duplicate_id": exact_duplicate.id,
                "similarity_score": 1.0
            }
        
        # 2. Vérification par similarité
        similar_id = cls.is_duplicate_by_similarity(
            db, question, context, source_url, similarity_threshold
        )
        
        if similar_id:
            # Calculer le score de similarité pour information
            similar_record = db.query(cls).filter(cls.id == similar_id).first()
            existing_question = similar_record.input.get('question', '')
            similarity_score = SequenceMatcher(None, question, existing_question).ratio()
            
            return {
                "type": "similar",
                "duplicate_id": similar_id,
                "similarity_score": similarity_score
            }
        
        return {
            "type": "new",
            "duplicate_id": None,
            "similarity_score": 0.0
        }
    
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
        index: int = 0,
    ) -> "QASource":
        if not question or not answer:
            raise ValueError("Question and answer are required")
        
        # Générer l'ID basé sur le contenu
        qa_id = cls.compute_hash_from_content(question, answer, context, source_url)
        
        return cls(
            id=qa_id,
            input={
                "question": question,
                "context": context,
                "source_url": source_url,
                "index": index
            },
            expected_output={
                "answer": answer,
                "confidence": float(confidence)
            },
            source_trace_id=source_trace_id,
            page_snapshot_id=page_snapshot_id,
            qa_metadata={
                "generation_timestamp": datetime.now(timezone.utc).isoformat(),
                "context_length": len(context) if context else 0,
                "question_length": len(question),
                "answer_length": len(answer),
                "content_hash": qa_id
            }
        )

    def to_langfuse_dataset_item(self) -> Dict[str, Any]:
        """Convert to Langfuse Dataset Item format"""
        item = {
            "input": self.input,
            "id": self.id
        }

        if self.expected_output:
            item["expected_output"] = self.expected_output

        if self.qa_metadata:
            item["metadata"] = self.qa_metadata
        
        return item
