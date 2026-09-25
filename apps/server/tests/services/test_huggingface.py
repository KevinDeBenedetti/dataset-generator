"""Tests for the Hugging Face export.

The Hub is never contacted: a fake ``HfApi`` records what would have been sent,
which is what the assertions are about — that the repo is created private, that
an already-public repo stops the export, and what the uploaded files contain.
"""

import json
from unittest.mock import patch

import pytest

from server.core.config import config
from server.services import huggingface as hf
from server.services.huggingface import (
    DATA_PATH_IN_REPO,
    HuggingFaceNotConfiguredError,
    HuggingFaceRepoPublicError,
    export_dataset_to_hub,
    is_huggingface_configured,
    resolve_repo_id,
    slugify,
)


class FakeRepoInfo:
    def __init__(self, private: bool):
        self.private = private


class FakeHfApi:
    """Stand-in for HfApi: records calls, never touches the network."""

    def __init__(self, *, existing_private=None, whoami_name="kevin"):
        # None → the repo doesn't exist yet; True/False → it does, with that
        # visibility (what create_repo(exist_ok=True) silently leaves alone).
        self.existing_private = existing_private
        self.whoami_name = whoami_name
        self.created: list[dict] = []
        self.uploads: list[dict] = []

    def whoami(self):
        return {"name": self.whoami_name}

    def create_repo(self, repo_id, **kwargs):
        self.created.append({"repo_id": repo_id, **kwargs})
        if self.existing_private is None:
            self.existing_private = kwargs.get("private", False)
        return f"https://huggingface.co/datasets/{repo_id}"

    def repo_info(self, repo_id, **kwargs):
        return FakeRepoInfo(bool(self.existing_private))

    def upload_file(self, *, path_or_fileobj, path_in_repo, repo_id, **kwargs):
        self.uploads.append(
            {
                "path_in_repo": path_in_repo,
                "repo_id": repo_id,
                "content": path_or_fileobj,
                **kwargs,
            }
        )


def _pair(pair_id, question, **overrides):
    pair = {
        "id": pair_id,
        "question": question,
        "answer": "An answer long enough to be useful.",
        "context": "Some context.",
        "source_url": "https://example.com/a",
        "confidence": 0.9,
        "created_at": None,
        "metadata": {},
    }
    pair.update(overrides)
    return pair


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setattr(config, "hf_token", "hf_test_token")
    monkeypatch.setattr(config, "hf_namespace", "")


@pytest.fixture
def api(monkeypatch):
    fake = FakeHfApi()
    monkeypatch.setattr(hf, "_api", lambda: fake)
    return fake


def _stub_dataset(pairs, target_language="fr"):
    """Patch the store reads the export depends on."""
    return (
        patch.object(
            hf,
            "get_dataset_view",
            return_value={"name": "ds", "target_language": target_language},
        ),
        patch.object(hf, "get_dataset_pairs", return_value=pairs),
    )


# --- configuration -----------------------------------------------------------


def test_not_configured_without_a_token(monkeypatch):
    monkeypatch.setattr(config, "hf_token", "")
    assert is_huggingface_configured() is False
    with pytest.raises(HuggingFaceNotConfiguredError, match="HF_TOKEN"):
        export_dataset_to_hub("ds")


def test_slugify_makes_a_valid_repo_name():
    assert slugify("Docs FR / v2") == "Docs-FR-v2"
    assert slugify("!!!") == "dataset"


def test_repo_id_defaults_to_the_token_account(token, api):
    assert resolve_repo_id("Docs FR") == "kevin/Docs-FR"


def test_repo_id_uses_the_configured_namespace(token, api, monkeypatch):
    monkeypatch.setattr(config, "hf_namespace", "my-org")
    assert resolve_repo_id("Docs FR") == "my-org/Docs-FR"


def test_explicit_repo_id_wins(token, api):
    assert resolve_repo_id("Docs FR", "someone/else") == "someone/else"


# --- export ------------------------------------------------------------------


def test_export_creates_a_private_repo_and_uploads(token, api):
    view, pairs = _stub_dataset([_pair("a", "Q1?"), _pair("b", "Q2?")])
    with view, pairs:
        result = export_dataset_to_hub("ds")

    assert result["repo_id"] == "kevin/ds"
    assert result["private"] is True
    assert result["pairs_exported"] == 2
    assert result["url"] == "https://huggingface.co/datasets/kevin/ds"

    # Created as a private *dataset* repo.
    assert api.created[0]["private"] is True
    assert api.created[0]["repo_type"] == "dataset"

    paths = [u["path_in_repo"] for u in api.uploads]
    assert paths == [DATA_PATH_IN_REPO, "README.md"]
    assert all(u["repo_type"] == "dataset" for u in api.uploads)


def test_export_refuses_an_existing_public_repo(token, monkeypatch):
    """The whole point of the guard: `private=True` is ignored on an existing
    repo, so uploading into a public one would publish the dataset."""
    fake = FakeHfApi(existing_private=False)
    monkeypatch.setattr(hf, "_api", lambda: fake)

    view, pairs = _stub_dataset([_pair("a", "Q1?")])
    with view, pairs:
        with pytest.raises(
            HuggingFaceRepoPublicError, match="already exists and is public"
        ):
            export_dataset_to_hub("ds")

    # Nothing was sent.
    assert fake.uploads == []


def test_export_accepts_an_existing_private_repo(token, monkeypatch):
    fake = FakeHfApi(existing_private=True)
    monkeypatch.setattr(hf, "_api", lambda: fake)

    view, pairs = _stub_dataset([_pair("a", "Q1?")])
    with view, pairs:
        result = export_dataset_to_hub("ds")

    assert result["pairs_exported"] == 1
    assert len(fake.uploads) == 2


def test_export_unknown_dataset_raises(token, api):
    with patch.object(hf, "get_dataset_view", return_value=None):
        with pytest.raises(ValueError, match="not found"):
            export_dataset_to_hub("ghost")


def test_export_empty_dataset_raises(token, api):
    view, pairs = _stub_dataset([])
    with view, pairs:
        with pytest.raises(ValueError, match="no Q/A pairs"):
            export_dataset_to_hub("ds")


# --- payload -----------------------------------------------------------------


def test_uploaded_jsonl_has_one_object_per_pair(token, api):
    from datetime import datetime, timezone

    created = datetime(2026, 1, 2, tzinfo=timezone.utc)
    view, pairs = _stub_dataset(
        [
            _pair("a", "Q1?", created_at=created),
            _pair("b", "Q2?", source_url=None, confidence=None),
        ]
    )
    with view, pairs:
        export_dataset_to_hub("ds")

    body = api.uploads[0]["content"].decode("utf-8")
    rows = [json.loads(line) for line in body.strip().split("\n")]
    assert len(rows) == 2
    assert rows[0]["question"] == "Q1?"
    # Datetimes are serialised, not left as objects.
    assert rows[0]["created_at"] == created.isoformat()
    assert rows[1]["source_url"] is None
    assert rows[1]["confidence"] is None


def test_uploaded_jsonl_keeps_non_ascii_readable(token, api):
    view, pairs = _stub_dataset([_pair("a", "Où est la gare ?")])
    with view, pairs:
        export_dataset_to_hub("ds")

    body = api.uploads[0]["content"].decode("utf-8")
    assert "Où est la gare ?" in body


def test_dataset_card_points_the_viewer_at_the_data_file(token, api):
    view, pairs = _stub_dataset([_pair("a", "Q1?")], target_language="fr")
    with view, pairs:
        export_dataset_to_hub("ds")

    card = api.uploads[1]["content"].decode("utf-8")
    assert f"data_files: {DATA_PATH_IN_REPO}" in card
    assert "- fr" in card
    assert "This dataset is **private**." in card
    # The sources actually used are listed.
    assert "https://example.com/a" in card
