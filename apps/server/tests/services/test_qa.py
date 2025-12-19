"""Tests for QA service"""

import pytest
from unittest.mock import Mock, patch
from sqlalchemy.orm import Session

from server.services.qa import QAService
from server.models.dataset import QASource, Dataset


@pytest.fixture
def qa_service(db: Session):
    """Create a QAService instance"""
    return QAService(db)


@pytest.fixture
def sample_dataset(db: Session):
    """Create a sample dataset"""
    dataset = Dataset(name="test_dataset", description="Test dataset")
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return dataset


@pytest.fixture
def sample_qa_source(db: Session, sample_dataset):
    """Create a sample QASource"""
    qa = QASource.from_qa_generation(
        question="What is Python?",
        answer="A programming language",
        context="Python is a high-level programming language.",
        source_url="https://example.com",
        dataset_id=sample_dataset.id,
        page_snapshot_id="1",
    )
    qa.model = "gpt-4o-mini"
    qa.dataset_name = sample_dataset.name
    db.add(qa)
    db.commit()
    db.refresh(qa)
    return qa


class TestQAService:
    """Tests for QAService class"""

    def test_add_qa_source(self, qa_service: QAService, db: Session, sample_dataset):
        """Test adding a new QASource"""
        qa = QASource.from_qa_generation(
            question="What is FastAPI?",
            answer="A modern web framework",
            context="FastAPI is a modern, fast web framework for building APIs.",
            source_url="https://example.com",
            dataset_id=sample_dataset.id,
            page_snapshot_id="1",
        )
        qa.model = "gpt-4o-mini"
        qa.dataset_name = sample_dataset.name

        result = qa_service.add_qa_source(qa)

        assert result.id is not None
        assert result.question == "What is FastAPI?"
        assert result.answer == "A modern web framework"

    def test_delete_qa_source(
        self, qa_service: QAService, sample_qa_source: QASource, db: Session
    ):
        """Test deleting a QASource"""
        qa_id = str(sample_qa_source.id)

        qa_service.delete_qa_source(qa_id)

        # Verify it's deleted
        deleted_qa = db.query(QASource).filter(QASource.id == qa_id).first()
        assert deleted_qa is None

    def test_delete_nonexistent_qa_source(self, qa_service: QAService):
        """Test deleting a non-existent QASource (should not raise error)"""
        qa_service.delete_qa_source("nonexistent-id")
        # Should complete without error

    def test_update_qa_source(self, qa_service: QAService, sample_qa_source: QASource):
        """Test updating a QASource"""
        updates = {
            "input": {**sample_qa_source.input, "question": "What is Python used for?"},
            "expected_output": {**sample_qa_source.expected_output, "confidence": 0.95},
        }

        result = qa_service.update_qa_source(str(sample_qa_source.id), updates)

        assert result.question == "What is Python used for?"
        assert result.confidence == 0.95

    def test_update_qa_source_not_found(self, qa_service: QAService):
        """Test updating a non-existent QASource"""
        with pytest.raises(ValueError, match="not found"):
            qa_service.update_qa_source("nonexistent-id", {"question": "New question"})

    def test_get_qa_source(self, qa_service: QAService, sample_qa_source: QASource):
        """Test retrieving a QASource by ID"""
        result = qa_service.get_qa_source(str(sample_qa_source.id))

        assert result.id == sample_qa_source.id
        assert result.question == sample_qa_source.question

    def test_get_qa_source_not_found(self, qa_service: QAService):
        """Test retrieving a non-existent QASource"""
        with pytest.raises(ValueError, match="not found"):
            qa_service.get_qa_source("nonexistent-id")

    def test_process_qa_pairs_new_items(
        self, qa_service: QAService, db: Session, sample_dataset
    ):
        """Test processing new QA pairs without duplicates"""
        # Create mock QA items
        mock_qa1 = Mock()
        mock_qa1.question = "What is Docker?"
        mock_qa1.answer = "A containerization platform"
        mock_qa1.confidence = 0.9

        mock_qa2 = Mock()
        mock_qa2.question = "What is Kubernetes?"
        mock_qa2.answer = "An orchestration system"
        mock_qa2.confidence = 0.85

        result = qa_service.process_qa_pairs(
            qa_list=[mock_qa1, mock_qa2],
            cleaned_text="Docker and Kubernetes are important DevOps tools.",
            url="https://example.com",
            page_snapshot_id="1",
            dataset_name=sample_dataset.name,
            model="gpt-4o-mini",
            dataset_id=sample_dataset.id,
            similarity_threshold=0.9,
        )

        assert result["total"] == 2
        assert result["exact_duplicates"] == 0
        assert result["similar_duplicates"] == 0

        # Verify QA records were saved
        qa_records = (
            db.query(QASource).filter(QASource.dataset_id == sample_dataset.id).all()
        )
        assert len(qa_records) == 2

    def test_process_qa_pairs_exact_duplicate(
        self, qa_service: QAService, db: Session, sample_dataset, sample_qa_source
    ):
        """Test processing QA pairs with exact duplicate"""
        mock_qa = Mock()
        mock_qa.question = sample_qa_source.question
        mock_qa.answer = sample_qa_source.answer

        result = qa_service.process_qa_pairs(
            qa_list=[mock_qa],
            cleaned_text=sample_qa_source.context,
            url=sample_qa_source.source_url,
            page_snapshot_id="1",
            dataset_name=sample_dataset.name,
            model="gpt-4o-mini",
            dataset_id=sample_dataset.id,
            similarity_threshold=0.9,
        )

        assert result["exact_duplicates"] == 1
        assert result["total"] == 0

    @patch("server.models.dataset.QASource.check_for_duplicates")
    def test_process_qa_pairs_similar_duplicate(
        self, mock_check_duplicates, qa_service: QAService, db: Session, sample_dataset
    ):
        """Test processing QA pairs with similar duplicate"""
        # Mock duplicate check to return similar
        mock_check_duplicates.return_value = {
            "type": "similar",
            "duplicate_id": "similar-id",
            "similarity_score": 0.92,
        }

        mock_qa = Mock()
        mock_qa.question = "What exactly is Python?"
        mock_qa.answer = "Python is a programming language"

        result = qa_service.process_qa_pairs(
            qa_list=[mock_qa],
            cleaned_text="Python programming",
            url="https://example.com",
            page_snapshot_id="1",
            dataset_name=sample_dataset.name,
            model="gpt-4o-mini",
            dataset_id=sample_dataset.id,
            similarity_threshold=0.9,
        )

        assert result["similar_duplicates"] == 1
        assert result["total"] == 0

    def test_process_qa_pairs_without_confidence(
        self, qa_service: QAService, db: Session, sample_dataset
    ):
        """Test processing QA pairs without confidence attribute"""
        mock_qa = Mock(spec=["question", "answer"])  # No confidence attribute
        mock_qa.question = "What is Redis?"
        mock_qa.answer = "An in-memory database"

        result = qa_service.process_qa_pairs(
            qa_list=[mock_qa],
            cleaned_text="Redis is fast",
            url="https://example.com",
            page_snapshot_id="1",
            dataset_name=sample_dataset.name,
            model="gpt-4o-mini",
            dataset_id=sample_dataset.id,
            similarity_threshold=0.9,
        )

        assert result["total"] == 1
        # Should use default confidence of 1.0
        qa_records = (
            db.query(QASource).filter(QASource.dataset_id == sample_dataset.id).all()
        )
        redis_qa = [qa for qa in qa_records if qa.question == "What is Redis?"][0]
        assert redis_qa.confidence == 1.0

    def test_process_qa_pairs_mixed_results(
        self, qa_service: QAService, db: Session, sample_dataset, sample_qa_source
    ):
        """Test processing QA pairs with mixed results (new, exact, similar)"""
        # First QA - new
        mock_qa1 = Mock()
        mock_qa1.question = "New question 1?"
        mock_qa1.answer = "New answer 1"
        mock_qa1.confidence = 0.9

        # Second QA - exact duplicate
        mock_qa2 = Mock()
        mock_qa2.question = sample_qa_source.question
        mock_qa2.answer = sample_qa_source.answer
        mock_qa2.confidence = 0.9  # Add confidence to avoid Mock in getattr

        # Third QA - new
        mock_qa3 = Mock()
        mock_qa3.question = "New question 2?"
        mock_qa3.answer = "New answer 2"
        mock_qa3.confidence = 0.8

        result = qa_service.process_qa_pairs(
            qa_list=[mock_qa1, mock_qa2, mock_qa3],
            cleaned_text=sample_qa_source.context,  # Use same context as sample for duplicate detection
            url=sample_qa_source.source_url,  # Use same URL for duplicate detection
            page_snapshot_id="1",
            dataset_name=sample_dataset.name,
            model="gpt-4o-mini",
            dataset_id=sample_dataset.id,
            similarity_threshold=0.9,
        )

        assert result["total"] == 2  # Two new items
        assert result["exact_duplicates"] == 1

    def test_process_qa_pairs_empty_list(
        self, qa_service: QAService, db: Session, sample_dataset
    ):
        """Test processing empty QA list"""
        result = qa_service.process_qa_pairs(
            qa_list=[],
            cleaned_text="Some text",
            url="https://example.com",
            page_snapshot_id="1",
            dataset_name=sample_dataset.name,
            model="gpt-4o-mini",
            dataset_id=sample_dataset.id,
            similarity_threshold=0.9,
        )

        assert result["total"] == 0
        assert result["exact_duplicates"] == 0
        assert result["similar_duplicates"] == 0

    def test_process_qa_pairs_custom_similarity_threshold(
        self, qa_service: QAService, db: Session, sample_dataset
    ):
        """Test processing with custom similarity threshold"""
        mock_qa = Mock()
        mock_qa.question = "What is PostgreSQL?"
        mock_qa.answer = "A relational database"
        mock_qa.confidence = 0.9

        result = qa_service.process_qa_pairs(
            qa_list=[mock_qa],
            cleaned_text="PostgreSQL is a powerful database",
            url="https://example.com",
            page_snapshot_id="1",
            dataset_name=sample_dataset.name,
            model="gpt-4o-mini",
            dataset_id=sample_dataset.id,
            similarity_threshold=0.75,  # Lower threshold
        )

        assert result["total"] == 1
