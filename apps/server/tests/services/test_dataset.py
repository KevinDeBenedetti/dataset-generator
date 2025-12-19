"""
Tests for dataset service.
"""

import pytest
from sqlalchemy.orm import Session

from server.models.dataset import Dataset, QASource
from server.services.dataset import (
    DatasetService,
    get_datasets,
    get_dataset_by_id,
    analyze_dataset_similarities,
    clean_dataset_similarities,
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

    result = get_dataset_by_id(test_db, dataset.id)

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
            dataset_id=dataset.id,
            index=i,
        )
        test_db.add(qa)
    test_db.commit()

    result = get_dataset_by_id(test_db, dataset.id)

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

    result = analyze_dataset_similarities(test_db, dataset.id, threshold=0.8)

    # Should handle empty dataset gracefully
    assert result is not None


def test_clean_dataset_similarities_not_found(test_db: Session):
    """Test clean similarities with non-existent dataset."""
    with pytest.raises(ValueError, match="not found"):
        clean_dataset_similarities(test_db, "non-existent-id")
