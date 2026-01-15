"""
Tests for dataset service.
"""

import pytest
from sqlalchemy.orm import Session

from server.models.dataset import Dataset, QASource
from server.services.dataset import (
    DatasetService,
    analyze_dataset_similarities,
    clean_dataset_similarities,
    get_dataset_by_id,
    get_datasets,
)


def test_dataset_service_get_or_create_new(test_db: Session):
    """Test getting or creating a new dataset."""
    service = DatasetService(test_db)
    dataset = service.get_or_create_dataset("new_dataset", "New description")

    assert dataset is not None
    assert dataset.name == "new_dataset"
    assert dataset.description == "New description"
    assert dataset.id is not None


def test_dataset_service_get_or_create_existing(test_db: Session):
    """Test getting an existing dataset."""
    # Create dataset first
    existing = Dataset(name="existing_dataset", description="Original description")
    test_db.add(existing)
    test_db.commit()
    test_db.refresh(existing)

    service = DatasetService(test_db)
    dataset = service.get_or_create_dataset("existing_dataset", "New description")

    # Should return existing dataset with original description
    assert dataset.id == existing.id
    assert dataset.description == "Original description"


def test_dataset_service_delete_dataset(test_db: Session):
    """Test deleting a dataset."""
    service = DatasetService(test_db)
    dataset = Dataset(name="to_delete")
    test_db.add(dataset)
    test_db.commit()
    test_db.refresh(dataset)

    service.delete_dataset(dataset)

    # Verify deletion
    deleted = test_db.query(Dataset).filter(Dataset.id == dataset.id).first()
    assert deleted is None


def test_dataset_service_update_description(test_db: Session):
    """Test updating dataset description."""
    service = DatasetService(test_db)
    dataset = Dataset(name="test_dataset", description="Old description")
    test_db.add(dataset)
    test_db.commit()
    test_db.refresh(dataset)

    updated = service.update_dataset_description(dataset, "New description")

    assert updated.description == "New description"
    assert updated.id == dataset.id


def test_get_datasets_empty(test_db: Session):
    """Test getting datasets when none exist."""
    result = get_datasets(test_db)
    assert result == []


def test_get_datasets(test_db: Session):
    """Test getting all datasets."""
    # Create some datasets
    datasets = [
        Dataset(name="dataset1", description="Desc 1"),
        Dataset(name="dataset2", description="Desc 2"),
        Dataset(name="dataset3", description="Desc 3"),
    ]
    for ds in datasets:
        test_db.add(ds)
    test_db.commit()

    result = get_datasets(test_db)

    assert len(result) == 3
    assert all("id" in item for item in result)
    assert all("name" in item for item in result)
    assert all("description" in item for item in result)


def test_get_dataset_by_id_success(test_db: Session):
    """Test getting dataset by ID."""
    dataset = Dataset(name="test_dataset", description="Test description")
    test_db.add(dataset)
    test_db.commit()
    test_db.refresh(dataset)

    result = get_dataset_by_id(test_db, str(dataset.id))

    assert result is not None
    assert result["id"] == dataset.id
    assert result["name"] == "test_dataset"
    assert result["qa_sources_count"] == 0


def test_get_dataset_by_id_not_found(test_db: Session):
    """Test getting non-existent dataset by ID."""
    result = get_dataset_by_id(test_db, "non-existent-id")
    assert result is None


def test_get_dataset_by_id_with_qa_count(test_db: Session):
    """Test that get_dataset_by_id returns correct QA count."""
    dataset = Dataset(name="test_dataset")
    test_db.add(dataset)
    test_db.commit()
    test_db.refresh(dataset)

    # Add some QA records
    for i in range(5):
        qa = QASource.from_qa_generation(
            question=f"Question {i}",
            answer=f"Answer {i}",
            context=f"Context {i}",
            confidence=0.9,
            source_url=f"https://example.com/{i}",
            dataset_id=str(dataset.id),
            index=i,
        )
        test_db.add(qa)
    test_db.commit()

    result = get_dataset_by_id(test_db, str(dataset.id))

    assert result is not None
    assert result["qa_sources_count"] == 5


def test_analyze_dataset_similarities_not_found(test_db: Session):
    """Test analyze similarities with non-existent dataset."""
    with pytest.raises(ValueError, match="not found"):
        analyze_dataset_similarities(test_db, "non-existent-id")


def test_analyze_dataset_similarities_empty(test_db: Session):
    """Test analyze similarities with empty dataset."""
    dataset = Dataset(name="empty_dataset")
    test_db.add(dataset)
    test_db.commit()
    test_db.refresh(dataset)

    result = analyze_dataset_similarities(test_db, str(dataset.id), threshold=0.8)

    # Should handle empty dataset gracefully
    assert result is not None


def test_clean_dataset_similarities_not_found(test_db: Session):
    """Test clean similarities with non-existent dataset."""
    with pytest.raises(ValueError, match="not found"):
        clean_dataset_similarities(test_db, "non-existent-id")


def test_analyze_dataset_similarities_with_similar_questions(test_db: Session):
    """Test analyze similarities finds similar questions."""
    dataset = Dataset(name="similar_dataset")
    test_db.add(dataset)
    test_db.commit()
    test_db.refresh(dataset)

    # Add similar questions
    qa1 = QASource.from_qa_generation(
        question="What is Python programming language?",
        answer="A high-level language",
        context="Context 1",
        source_url="https://example.com/1",
        dataset_id=str(dataset.id),
    )
    qa2 = QASource.from_qa_generation(
        question="What is Python programming?",
        answer="A scripting language",
        context="Context 2",
        source_url="https://example.com/2",
        dataset_id=str(dataset.id),
    )
    qa3 = QASource.from_qa_generation(
        question="What is JavaScript?",
        answer="A web language",
        context="Context 3",
        source_url="https://example.com/3",
        dataset_id=str(dataset.id),
    )
    test_db.add_all([qa1, qa2, qa3])
    test_db.commit()

    result = analyze_dataset_similarities(test_db, str(dataset.id), threshold=0.7)

    assert result["dataset_id"] == dataset.id
    assert result["total_records"] == 3
    assert result["similar_pairs_found"] >= 1
    assert len(result["similarities"]) >= 1


def test_analyze_dataset_similarities_no_similar(test_db: Session):
    """Test analyze similarities with no similar questions."""
    dataset = Dataset(name="unique_dataset")
    test_db.add(dataset)
    test_db.commit()
    test_db.refresh(dataset)

    # Add unique questions
    qa1 = QASource.from_qa_generation(
        question="What is Python?",
        answer="A language",
        context="Context 1",
        source_url="https://example.com/1",
        dataset_id=str(dataset.id),
    )
    qa2 = QASource.from_qa_generation(
        question="How do airplanes fly?",
        answer="Using aerodynamics",
        context="Context 2",
        source_url="https://example.com/2",
        dataset_id=str(dataset.id),
    )
    test_db.add_all([qa1, qa2])
    test_db.commit()

    result = analyze_dataset_similarities(test_db, str(dataset.id), threshold=0.9)

    assert result["similar_pairs_found"] == 0


def test_clean_dataset_similarities_empty_records(test_db: Session):
    """Test clean similarities with empty dataset."""
    dataset = Dataset(name="empty_clean_dataset")
    test_db.add(dataset)
    test_db.commit()
    test_db.refresh(dataset)

    with pytest.raises(ValueError, match="No records found"):
        clean_dataset_similarities(test_db, str(dataset.id))


def test_clean_dataset_similarities_removes_duplicates(test_db: Session):
    """Test clean similarities removes duplicate questions."""
    dataset = Dataset(name="clean_test_dataset")
    test_db.add(dataset)
    test_db.commit()
    test_db.refresh(dataset)

    # Add very similar questions (one with higher confidence)
    qa1 = QASource.from_qa_generation(
        question="What is Python programming language?",
        answer="A high-level language",
        context="Context 1",
        confidence=0.9,
        source_url="https://example.com/1",
        dataset_id=str(dataset.id),
    )
    qa2 = QASource.from_qa_generation(
        question="What is Python programming language?",
        answer="A scripting language",
        context="Context 2",
        confidence=0.5,
        source_url="https://example.com/2",
        dataset_id=str(dataset.id),
    )
    test_db.add_all([qa1, qa2])
    test_db.commit()

    result = clean_dataset_similarities(test_db, str(dataset.id), threshold=0.9)

    assert result["removed_records"] >= 1
    # Verify one record was removed
    remaining = (
        test_db.query(QASource).filter(QASource.dataset_id == dataset.id).count()
    )
    assert remaining == 1


def test_clean_dataset_similarities_keeps_higher_confidence(test_db: Session):
    """Test clean similarities keeps record with higher confidence."""
    dataset = Dataset(name="confidence_test")
    test_db.add(dataset)
    test_db.commit()
    test_db.refresh(dataset)

    # Add identical questions with different confidence
    qa_low = QASource.from_qa_generation(
        question="Exactly the same question",
        answer="Low confidence answer",
        context="Context 1",
        confidence=0.3,
        source_url="https://example.com/low",
        dataset_id=str(dataset.id),
    )
    qa_high = QASource.from_qa_generation(
        question="Exactly the same question",
        answer="High confidence answer",
        context="Context 2",
        confidence=0.95,
        source_url="https://example.com/high",
        dataset_id=str(dataset.id),
    )
    test_db.add_all([qa_low, qa_high])
    test_db.commit()

    clean_dataset_similarities(test_db, str(dataset.id), threshold=0.99)

    # Verify the high confidence one was kept
    remaining = (
        test_db.query(QASource).filter(QASource.dataset_id == dataset.id).first()
    )
    assert remaining is not None
    assert remaining.expected_output.get("confidence") == 0.95


def test_clean_dataset_similarities_no_duplicates(test_db: Session):
    """Test clean similarities with no duplicates to remove."""
    dataset = Dataset(name="no_dup_dataset")
    test_db.add(dataset)
    test_db.commit()
    test_db.refresh(dataset)

    qa1 = QASource.from_qa_generation(
        question="What is Python?",
        answer="A language",
        context="Context 1",
        source_url="https://example.com/1",
        dataset_id=str(dataset.id),
    )
    qa2 = QASource.from_qa_generation(
        question="What is JavaScript?",
        answer="Another language",
        context="Context 2",
        source_url="https://example.com/2",
        dataset_id=str(dataset.id),
    )
    test_db.add_all([qa1, qa2])
    test_db.commit()

    result = clean_dataset_similarities(test_db, str(dataset.id), threshold=0.99)

    assert result["removed_records"] == 0
    assert result["total_records"] == 2
