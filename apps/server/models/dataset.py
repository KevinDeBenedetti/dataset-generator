import uuid
import hashlib
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from sqlalchemy import String, DateTime, JSON, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from server.core.database import Base
from server.services.dedup import QAEntry


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Target language of the dataset's generations (ISO code, e.g. "en", "fr").
    # Set on the first generation; a best-effort dataset-level label.
    target_language: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class QASource(Base):
    __tablename__ = "qa_sources"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    dataset_name: Mapped[Optional[str]] = mapped_column(String, index=True)
    dataset_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("datasets.id"), index=True
    )
    source_trace_id: Mapped[Optional[str]] = mapped_column(String)
    # No longer FK-constrained: page_snapshots was dropped once the scraper
    # went stateless (see migration d1e2f3a4b5c6). Always null now — kept as
    # plain data rather than threading its removal through every call site
    # that still passes page_snapshot_id=None.
    page_snapshot_id: Mapped[Optional[str]] = mapped_column(String)
    input: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    expected_output: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    qa_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[Optional[str]] = mapped_column(String, default="ACTIVE", index=True)
    model: Mapped[Optional[str]] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    human_reviewed: Mapped[bool] = mapped_column(Boolean, default=False)

    @staticmethod
    def compute_hash_from_content(
        question: str, answer: str, context: str, source_url: str = ""
    ) -> str:
        question_normalized = " ".join(question.strip().split())
        context_normalized = " ".join(context.strip().split())

        content = f"{question_normalized}|{context_normalized}|{source_url}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @classmethod
    def _to_entry(cls, record: "QASource") -> QAEntry:
        """Adapt a persisted row to the pure :class:`QAEntry` used for dedup.

        Used by :class:`server.services.qa.QAService` to build its in-memory
        dedup pool once per pipeline run (see that module for why the DB-query
        classmethods that used to live here were removed).
        """
        source = record.input or {}
        return QAEntry(
            hash=record.id,
            question=source.get("question", ""),
            context=source.get("context", ""),
            source_url=source.get("source_url", ""),
        )

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
        dataset_id: Optional[str] = None,  # Added dataset_id parameter
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
            dataset_id=dataset_id,  # Using the dataset_id
            qa_metadata={
                "generation_timestamp": datetime.now(timezone.utc).isoformat(),
                "context_length": len(context) if context else 0,
                "question_length": len(question),
                "answer_length": len(answer),
                "content_hash": qa_id,
            },
        )

    @property
    def question(self) -> str:
        """Get question from input JSON"""
        return self.input.get("question", "")

    @property
    def answer(self) -> str:
        """Get answer from expected_output JSON"""
        return self.expected_output.get("answer", "")

    @property
    def context(self) -> str:
        """Get context from input JSON"""
        return self.input.get("context", "")

    @property
    def source_url(self) -> str:
        """Get source_url from input JSON"""
        return self.input.get("source_url", "")

    @property
    def confidence(self) -> float:
        """Get confidence from expected_output JSON"""
        return self.expected_output.get("confidence", 1.0)

    def to_langfuse_dataset_item(self) -> Dict[str, Any]:
        """Convert to Langfuse Dataset Item format"""
        item = {"input": self.input, "id": self.id}

        if self.expected_output:
            item["expected_output"] = self.expected_output

        if self.qa_metadata:
            item["metadata"] = self.qa_metadata

        return item
