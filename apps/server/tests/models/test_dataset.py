"""
Tests for Dataset and QASource models.
"""
import pytest
from datetime import datetime
from sqlalchemy.orm import Session

from server.models.dataset import Dataset, QASource


def test_dataset_creation(test_db: Session):
    """Test creating a dataset."""
    dataset = Dataset(name="test_dataset", description="Test description")
    test_db.add(dataset)
    test_db.commit()
    test_db.refresh(dataset)

    assert dataset.id is not None
    assert dataset.name == "test_dataset"
    assert dataset.description == "Test description"
    assert isinstance(dataset.created_at, datetime)


def test_dataset_creation_without_description(test_db: Session):
    """Test creating a dataset without description."""
    dataset = Dataset(name="test_dataset")
    test_db.add(dataset)
    test_db.commit()
    test_db.refresh(dataset)

    assert dataset.description is None


def test_qa_source_from_qa_generation(test_db: Session):
    """Test creating QASource from qa_generation."""
    dataset = Dataset(name="test_dataset")
    test_db.add(dataset)
    test_db.commit()

    qa = QASource.from_qa_generation(
        question="What is Python?",
        answer="Python is a programming language.",
        context="Python is widely used for web development.",
        confidence=0.95,
        source_url="https://example.com/python",
        dataset_id=dataset.id,
        index=0,
    )
    test_db.add(qa)
    test_db.commit()
    test_db.refresh(qa)

    assert qa.id is not None
    assert qa.input["question"] == "What is Python?"
    assert qa.input["context"] == "Python is widely used for web development."
    assert qa.input["source_url"] == "https://example.com/python"
    assert qa.expected_output["answer"] == "Python is a programming language."
    assert qa.expected_output["confidence"] == 0.95
    assert qa.dataset_id == dataset.id


def test_qa_source_validation_missing_question():
    """Test that QASource requires question."""
    with pytest.raises(ValueError, match="Question and answer are required"):
        QASource.from_qa_generation(
            question="",
            answer="Some answer",
            context="Some context",
            confidence=0.9,
        )


def test_qa_source_validation_missing_answer():
    """Test that QASource requires answer."""
    with pytest.raises(ValueError, match="Question and answer are required"):
        QASource.from_qa_generation(
            question="Some question",
            answer="",
            context="Some context",
            confidence=0.9,
        )


def test_qa_source_compute_hash():
    """Test hash computation for QASource."""
    hash1 = QASource.compute_hash_from_content(
        question="What is AI?",
        answer="Artificial Intelligence",
        context="AI is a field of computer science.",
        source_url="https://example.com",
    )
    
    hash2 = QASource.compute_hash_from_content(
        question="What is AI?",
        answer="Artificial Intelligence",
        context="AI is a field of computer science.",
        source_url="https://example.com",
    )
    
    # Same content should produce same hash
    assert hash1 == hash2
    assert isinstance(hash1, str)
    assert len(hash1) == 64  # SHA256 produces 64 character hex string


def test_qa_source_hash_different_for_different_content():
    """Test that different content produces different hashes."""
    hash1 = QASource.compute_hash_from_content(
        question="What is AI?",
        answer="Artificial Intelligence",
        context="Context 1",
        source_url="https://example.com",
    )
    
    hash2 = QASource.compute_hash_from_content(
        question="What is ML?",
        answer="Machine Learning",
        context="Context 2",
        source_url="https://example.com",
    )
    
    assert hash1 != hash2


def test_qa_source_check_for_duplicates_exact(test_db: Session):
    """Test duplicate detection by exact hash."""
    dataset = Dataset(name="test_dataset")
    test_db.add(dataset)
    test_db.commit()

    # Create first QA
    qa1 = QASource.from_qa_generation(
        question="What is Python?",
        answer="A programming language",
        context="Python context",
        confidence=0.9,
        source_url="https://example.com",
        dataset_id=dataset.id,
    )
    test_db.add(qa1)
    test_db.commit()

    # Check for duplicate with same content
    duplicate_check = QASource.check_for_duplicates(
        test_db,
        question="What is Python?",
        answer="A programming language",
        context="Python context",
        source_url="https://example.com",
    )
    
    assert duplicate_check["type"] == "exact"
    assert duplicate_check["duplicate_id"] == qa1.id
    assert duplicate_check["similarity_score"] == 1.0


def test_qa_source_check_for_duplicates_new(test_db: Session):
    """Test that new content is not detected as duplicate."""
    dataset = Dataset(name="test_dataset")
    test_db.add(dataset)
    test_db.commit()

    # Create first QA
    qa1 = QASource.from_qa_generation(
        question="What is Python?",
        answer="A programming language",
        context="Python context",
        confidence=0.9,
        source_url="https://example.com",
        dataset_id=dataset.id,
    )
    test_db.add(qa1)
    test_db.commit()

    # Check with completely different content
    duplicate_check = QASource.check_for_duplicates(
        test_db,
        question="What is Java?",
        answer="Another programming language",
        context="Java context",
        source_url="https://example.com/java",
    )
    
    assert duplicate_check["type"] == "new"
    assert duplicate_check["duplicate_id"] is None
    assert duplicate_check["similarity_score"] == 0.0


def test_qa_source_check_for_duplicates_similar(test_db: Session):
    """Test duplicate detection by similarity."""
    dataset = Dataset(name="test_dataset")
    test_db.add(dataset)
    test_db.commit()

    # Create first QA
    qa1 = QASource.from_qa_generation(
        question="What is Python programming?",
        answer="A programming language",
        context="Python is great for web development.",
        confidence=0.9,
        source_url="https://example.com",
        dataset_id=dataset.id,
    )
    test_db.add(qa1)
    test_db.commit()

    # Check with very similar question (but not exact)
    duplicate_check = QASource.check_for_duplicates(
        test_db,
        question="What is Python programming?",  # Very similar
        answer="Different answer",
        context="Python is great for web development.",  # Same context
        source_url="https://example.com",  # Same URL
        similarity_threshold=0.9,
    )
    
    # This should detect as similar if similarity is high enough
    assert duplicate_check["type"] in ["similar", "exact"]


def test_qa_source_to_langfuse_dataset_item(test_db: Session):
    """Test conversion to Langfuse dataset item format."""
    dataset = Dataset(name="test_dataset")
    test_db.add(dataset)
    test_db.commit()

    qa = QASource.from_qa_generation(
        question="Test question?",
        answer="Test answer",
        context="Test context",
        confidence=0.95,
        source_url="https://example.com",
        dataset_id=dataset.id,
    )
    test_db.add(qa)
    test_db.commit()
    test_db.refresh(qa)

    langfuse_item = qa.to_langfuse_dataset_item()
    
    assert "input" in langfuse_item
    assert "id" in langfuse_item
    assert "expected_output" in langfuse_item
    assert "metadata" in langfuse_item
    assert langfuse_item["id"] == qa.id
    assert langfuse_item["input"] == qa.input
    assert langfuse_item["expected_output"] == qa.expected_output


def test_qa_source_metadata_generation(test_db: Session):
    """Test that QASource generates proper metadata."""
    dataset = Dataset(name="test_dataset")
    test_db.add(dataset)
    test_db.commit()

    question = "What is machine learning?"
    answer = "ML is a subset of AI that enables computers to learn from data."
    context = "Machine learning is a powerful technology used in many applications."

    qa = QASource.from_qa_generation(
        question=question,
        answer=answer,
        context=context,
        confidence=0.92,
        source_url="https://example.com/ml",
        dataset_id=dataset.id,
    )
    test_db.add(qa)
    test_db.commit()
    test_db.refresh(qa)

    metadata = qa.qa_metadata
    assert "generation_timestamp" in metadata
    assert "context_length" in metadata
    assert "question_length" in metadata
    assert "answer_length" in metadata
    assert "content_hash" in metadata
    assert metadata["context_length"] == len(context)
    assert metadata["question_length"] == len(question)
    assert metadata["answer_length"] == len(answer)
