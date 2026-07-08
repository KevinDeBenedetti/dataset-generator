"""
Tests for dataset service.
"""

from sqlalchemy.orm import Session

from server.models.dataset import Dataset, QASource
from server.services.dataset import DatasetService, get_qa_records_for_dataset


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


def test_get_qa_records_for_dataset(test_db: Session):
    """Returns only the QASource rows belonging to the given dataset."""
    dataset = Dataset(name="ds-a")
    other_dataset = Dataset(name="ds-b")
    test_db.add_all([dataset, other_dataset])
    test_db.commit()
    test_db.refresh(dataset)
    test_db.refresh(other_dataset)

    matching = [
        QASource.from_qa_generation(
            question=f"q{i}?",
            answer=f"a{i}",
            context=f"ctx{i}",
            source_url=f"https://example.com/{i}",
            dataset_id=str(dataset.id),
        )
        for i in range(2)
    ]
    unrelated = QASource.from_qa_generation(
        question="other?",
        answer="other answer",
        context="other ctx",
        source_url="https://example.com/other",
        dataset_id=str(other_dataset.id),
    )
    test_db.add_all([*matching, unrelated])
    test_db.commit()

    records = get_qa_records_for_dataset(test_db, dataset.id)

    assert {r.id for r in records} == {r.id for r in matching}


def test_get_qa_records_for_dataset_empty(test_db: Session):
    """Returns an empty list for a dataset with no QA pairs."""
    dataset = Dataset(name="empty-ds")
    test_db.add(dataset)
    test_db.commit()
    test_db.refresh(dataset)

    assert get_qa_records_for_dataset(test_db, dataset.id) == []


def test_get_or_create_dataset_persists_and_backfills_language(test_db: Session):
    """target_language is stored on create and backfilled when missing."""
    service = DatasetService(test_db)

    created = service.get_or_create_dataset("lang-new", "d", target_language="en")
    assert created.target_language == "en"

    # Existing dataset without a language gets backfilled.
    legacy = Dataset(name="legacy", description="d")
    test_db.add(legacy)
    test_db.commit()
    backfilled = service.get_or_create_dataset("legacy", target_language="de")
    assert backfilled.target_language == "de"
