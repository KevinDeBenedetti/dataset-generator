"""Tests for the Hugging Face export.

The Hub is never contacted: a fake ``HfApi`` records what would have been sent,
which is what the assertions are about — that the repo is created private, that
an already-public repo stops the export, and what the uploaded files contain.
"""

import json
from unittest.mock import patch

import pytest

from server.tests.creds import FULL, NONE, make_creds  # noqa: F401
from server.services import huggingface as hf
from server.services.huggingface import (
    DATA_PATH_IN_REPO,
    HuggingFaceNotConfiguredError,
    HuggingFaceRepoPublicError,
    export_dataset_to_hub,
    import_dataset_from_hub,
    is_huggingface_configured,
    list_user_datasets,
    qualify_repo_id,
    resolve_repo_id,
    slugify,
)

# The user the export/import acts for (the service is owner-scoped).
CREDS = make_creds(hf_token="hf_test_token")
OWNER = "owner-1"


class FakeRepoInfo:
    def __init__(self, private: bool):
        self.private = private


class FakeCardData:
    def __init__(self, **fields):
        self._fields = fields

    def to_dict(self):
        return dict(self._fields)


class FakeSibling:
    def __init__(self, rfilename):
        self.rfilename = rfilename


class FakeDatasetInfo:
    def __init__(
        self,
        id,
        private=False,
        downloads=0,
        likes=0,
        last_modified=None,
        author=None,
        gated=False,
        disabled=False,
        downloads_all_time=None,
        tags=None,
        description=None,
        siblings=None,
        used_storage=None,
        sha=None,
        created_at=None,
        card_data=None,
    ):
        self.id = id
        self.private = private
        self.downloads = downloads
        self.likes = likes
        self.last_modified = last_modified
        self.author = author
        self.gated = gated
        self.disabled = disabled
        self.downloads_all_time = downloads_all_time
        self.tags = tags
        self.description = description
        self.siblings = siblings
        self.used_storage = used_storage
        self.sha = sha
        self.created_at = created_at
        self.card_data = card_data


class FakeHfApi:
    """Stand-in for HfApi: records calls, never touches the network."""

    def __init__(self, *, existing_private=None, whoami_name="kevin", datasets=None):
        # None → the repo doesn't exist yet; True/False → it does, with that
        # visibility (what create_repo(exist_ok=True) silently leaves alone).
        self.existing_private = existing_private
        self.whoami_name = whoami_name
        self.created: list[dict] = []
        self.uploads: list[dict] = []
        self._datasets = datasets if datasets is not None else []
        self.list_datasets_calls: list[dict] = []

    def whoami(self):
        return {"name": self.whoami_name}

    def list_datasets(self, **kwargs):
        self.list_datasets_calls.append(kwargs)
        return iter(self._datasets)

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
def token():
    """The default CREDS carry a token and no namespace (kept for readability)."""


@pytest.fixture
def api(monkeypatch):
    fake = FakeHfApi()
    monkeypatch.setattr(hf, "_api", lambda creds: fake)
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
    assert is_huggingface_configured(NONE) is False
    assert is_huggingface_configured(CREDS) is True
    view, pairs = _stub_dataset([_pair("a", "Q1?")])
    with view, pairs, pytest.raises(HuggingFaceNotConfiguredError, match="Settings"):
        export_dataset_to_hub(OWNER, NONE, "ds")


def test_slugify_makes_a_valid_repo_name():
    assert slugify("Docs FR / v2") == "Docs-FR-v2"
    assert slugify("!!!") == "dataset"


def test_repo_id_defaults_to_the_token_account(token, api):
    assert resolve_repo_id(CREDS, "Docs FR") == "kevin/Docs-FR"


def test_repo_id_uses_the_configured_namespace(token, api):
    org = make_creds(hf_token="hf_test_token", hf_namespace="my-org")
    assert resolve_repo_id(org, "Docs FR") == "my-org/Docs-FR"


def test_explicit_repo_id_wins(token, api):
    assert resolve_repo_id(CREDS, "Docs FR", "someone/else") == "someone/else"


def test_qualify_repo_id_completes_a_bare_name(token, api):
    # A bare id 404s on commit/download/info: it needs its namespace.
    assert qualify_repo_id(CREDS, "github-personal") == "kevin/github-personal"
    assert qualify_repo_id(CREDS, "  github-personal ") == "kevin/github-personal"


def test_qualify_repo_id_prefers_the_configured_namespace(token, api):
    org = make_creds(hf_token="hf_test_token", hf_namespace="my-org")
    assert qualify_repo_id(org, "github-personal") == "my-org/github-personal"


def test_qualify_repo_id_keeps_a_full_id_without_calling_the_hub(token, monkeypatch):
    def no_hub(creds):
        raise AssertionError("a full id needs no Hub call")

    monkeypatch.setattr(hf, "_api", no_hub)
    assert qualify_repo_id(CREDS, "someone/else") == "someone/else"


def test_qualify_repo_id_needs_a_namespace(token, api, monkeypatch):
    monkeypatch.setattr(api, "whoami", lambda: {})
    with pytest.raises(HuggingFaceNotConfiguredError, match="namespace"):
        qualify_repo_id(CREDS, "github-personal")


# --- export ------------------------------------------------------------------


def test_export_creates_a_private_repo_and_uploads(token, api):
    view, pairs = _stub_dataset([_pair("a", "Q1?"), _pair("b", "Q2?")])
    with view, pairs:
        result = export_dataset_to_hub(OWNER, CREDS, "ds")

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
    monkeypatch.setattr(hf, "_api", lambda creds: fake)

    view, pairs = _stub_dataset([_pair("a", "Q1?")])
    with view, pairs:
        with pytest.raises(
            HuggingFaceRepoPublicError, match="already exists and is public"
        ):
            export_dataset_to_hub(OWNER, CREDS, "ds")

    # Nothing was sent.
    assert fake.uploads == []


def test_export_accepts_an_existing_private_repo(token, monkeypatch):
    fake = FakeHfApi(existing_private=True)
    monkeypatch.setattr(hf, "_api", lambda creds: fake)

    view, pairs = _stub_dataset([_pair("a", "Q1?")])
    with view, pairs:
        result = export_dataset_to_hub(OWNER, CREDS, "ds")

    assert result["pairs_exported"] == 1
    assert len(fake.uploads) == 2


def test_export_unknown_dataset_raises(token, api):
    with patch.object(hf, "get_dataset_view", return_value=None):
        with pytest.raises(ValueError, match="not found"):
            export_dataset_to_hub(OWNER, CREDS, "ghost")


def test_export_empty_dataset_raises(token, api):
    view, pairs = _stub_dataset([])
    with view, pairs:
        with pytest.raises(ValueError, match="no Q/A pairs"):
            export_dataset_to_hub(OWNER, CREDS, "ds")


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
        export_dataset_to_hub(OWNER, CREDS, "ds")

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
        export_dataset_to_hub(OWNER, CREDS, "ds")

    body = api.uploads[0]["content"].decode("utf-8")
    assert "Où est la gare ?" in body


# --- listing -------------------------------------------------------------


def test_list_user_datasets_not_configured_without_a_token():
    with pytest.raises(HuggingFaceNotConfiguredError, match="Settings"):
        list_user_datasets(NONE)


def test_list_user_datasets_uses_the_token_account(token, monkeypatch):
    fake = FakeHfApi(
        datasets=[
            FakeDatasetInfo("kevin/ds-a"),
            FakeDatasetInfo("kevin/ds-b", private=True),
        ]
    )
    monkeypatch.setattr(hf, "_api", lambda creds: fake)

    result = list_user_datasets(CREDS)

    assert result["namespace"] == "kevin"
    assert result["total"] == 2
    assert [d["id"] for d in result["datasets"]] == ["kevin/ds-a", "kevin/ds-b"]
    assert result["datasets"][0]["url"] == "https://huggingface.co/datasets/kevin/ds-a"
    assert result["datasets"][1]["private"] is True
    assert fake.list_datasets_calls[0]["author"] == "kevin"
    # Asks for everything the Hub knows, not just the default summary fields.
    assert fake.list_datasets_calls[0]["full"] is True


def test_list_user_datasets_surfaces_full_metadata(token, monkeypatch):
    from datetime import datetime, timezone

    created = datetime(2026, 1, 2, tzinfo=timezone.utc)
    modified = datetime(2026, 2, 3, tzinfo=timezone.utc)
    fake = FakeHfApi(
        datasets=[
            FakeDatasetInfo(
                "kevin/ds-a",
                author="kevin",
                downloads=42,
                downloads_all_time=1000,
                likes=7,
                gated="auto",
                tags=["synthetic", "question-answering"],
                description="Q/A pairs scraped from docs.",
                siblings=[FakeSibling("README.md"), FakeSibling("data/train.jsonl")],
                used_storage=123456,
                sha="abc123",
                created_at=created,
                last_modified=modified,
                card_data=FakeCardData(
                    pretty_name="Docs QA",
                    language=["fr"],
                    license="mit",
                    size_categories=["1K<n<10K"],
                ),
            )
        ]
    )
    monkeypatch.setattr(hf, "_api", lambda creds: fake)

    row = list_user_datasets(CREDS)["datasets"][0]

    assert row["author"] == "kevin"
    assert row["downloads"] == 42
    assert row["downloads_all_time"] == 1000
    assert row["likes"] == 7
    assert row["gated"] == "auto"
    assert row["tags"] == ["synthetic", "question-answering"]
    assert row["description"] == "Q/A pairs scraped from docs."
    assert row["file_count"] == 2
    assert row["used_storage"] == 123456
    assert row["sha"] == "abc123"
    assert row["created_at"] == created.isoformat()
    assert row["last_modified"] == modified.isoformat()
    assert row["pretty_name"] == "Docs QA"
    assert row["language"] == ["fr"]
    assert row["license"] == "mit"
    assert row["size_category"] == "1K<n<10K"


def test_list_user_datasets_handles_no_card(token, monkeypatch):
    fake = FakeHfApi(
        datasets=[FakeDatasetInfo("kevin/ds-a", card_data=None, siblings=None)]
    )
    monkeypatch.setattr(hf, "_api", lambda creds: fake)

    row = list_user_datasets(CREDS)["datasets"][0]

    assert row["pretty_name"] is None
    assert row["language"] is None
    assert row["license"] is None
    assert row["size_category"] is None
    assert row["file_count"] is None
    assert row["tags"] == []
    assert row["gated"] is False


def test_list_user_datasets_normalizes_a_multi_value_license(token, monkeypatch):
    """A list-valued `license` (a real, documented card pattern for datasets
    combining sources) must come back as a plain string: the schema types
    `HuggingFaceDataset.license` as `Optional[str]`, and a raw list there would
    fail response-model validation for the *whole* listing endpoint — after
    list_user_datasets(CREDS) already succeeded — taking every dataset down with it."""
    fake = FakeHfApi(
        datasets=[
            FakeDatasetInfo(
                "kevin/ds-a",
                card_data=FakeCardData(license=["mit", "cc-by-4.0"]),
            )
        ]
    )
    monkeypatch.setattr(hf, "_api", lambda creds: fake)

    row = list_user_datasets(CREDS)["datasets"][0]

    assert row["license"] == "mit, cc-by-4.0"
    assert isinstance(row["license"], str)


def test_list_user_datasets_uses_the_configured_namespace(token, monkeypatch):
    fake = FakeHfApi(datasets=[])
    monkeypatch.setattr(hf, "_api", lambda creds: fake)

    result = list_user_datasets(
        make_creds(hf_token="hf_test_token", hf_namespace="my-org")
    )

    assert result["namespace"] == "my-org"
    assert result["total"] == 0
    assert fake.list_datasets_calls[0]["author"] == "my-org"


def test_dataset_card_points_the_viewer_at_the_data_file(token, api):
    view, pairs = _stub_dataset([_pair("a", "Q1?")], target_language="fr")
    with view, pairs:
        export_dataset_to_hub(OWNER, CREDS, "ds")

    card = api.uploads[1]["content"].decode("utf-8")
    assert f"data_files: {DATA_PATH_IN_REPO}" in card
    assert "- fr" in card
    assert "This dataset is **private**." in card
    # The sources actually used are listed.
    assert "https://example.com/a" in card


# --- import --------------------------------------------------------------

SHA_A = "a" * 64
SHA_B = "b" * 64


def _jsonl(*rows) -> bytes:
    return ("\n".join(json.dumps(r) for r in rows) + "\n").encode("utf-8")


def _hub(files):
    """Patch the Hub reads: ``files`` maps repo paths to their bytes."""
    return (
        patch.object(hf, "_list_repo_files", return_value=list(files)),
        patch.object(
            hf, "_download_file", side_effect=lambda _creds, _repo, name: files[name]
        ),
    )


def _saved(files, repo="kevin/my-ds", **kwargs):
    """Run the import against fake repo ``files``; return (result, items, save)."""
    listing, download = _hub(files)
    with (
        listing,
        download,
        patch.object(
            hf, "save_generation", return_value={"created_count": 1, "version": 1}
        ) as save,
    ):
        result = import_dataset_from_hub(OWNER, CREDS, repo, **kwargs)
    # save_generation(owner_id, name, items, …): the items are the third argument.
    return result, save.call_args.args[2], save


def test_import_not_configured_without_a_token():
    with pytest.raises(HuggingFaceNotConfiguredError, match="Settings"):
        import_dataset_from_hub(OWNER, NONE, "kevin/ds")


def test_import_reads_the_apps_own_export_and_keeps_its_ids(token):
    raw = _jsonl(
        {
            "id": SHA_A,
            "question": "Q1?",
            "answer": "A1",
            "context": "C1",
            "source_url": "https://x/a",
            "confidence": 0.9,
        },
        {
            "id": SHA_B,
            "question": "Q2?",
            "answer": "A2",
            "context": "C2",
            "source_url": None,
        },
    )
    result, items, save = _saved({"README.md": b"# card", DATA_PATH_IN_REPO: raw})

    assert result["dataset_name"] == "my-ds"
    assert save.call_args.kwargs["source_url"] == "huggingface://kevin/my-ds"
    assert [i["id"] for i in items] == [SHA_A, SHA_B]
    assert items[0]["confidence"] == 0.9
    assert items[0]["metadata"] == {
        "imported_from": "kevin/my-ds",
        "file": DATA_PATH_IN_REPO,
    }
    # A row without a source falls back to the repo, not to None.
    assert items[1]["source_url"] == "huggingface://kevin/my-ds"


def test_import_finds_a_data_file_outside_data_dir(token):
    """The real-world case: a repo not written by this app's exporter keeps
    its file at the root, not at data/train.jsonl."""
    raw = _jsonl({"question": "Q1?", "answer": "A1"})
    _, items, _ = _saved({".gitattributes": b"", "train.jsonl": raw})
    assert [i["question"] for i in items] == ["Q1?"]


def test_import_ignores_dataset_metadata_files(token, monkeypatch):
    """`dataset_infos.json` ranks as `.json`, which outranks `.parquet` in the
    extension-priority pick — without excluding known metadata filenames it
    would be picked instead of the real data shard, and the import would fail
    with "no row maps onto a Q/A pair" even though the repo is fine."""
    monkeypatch.setattr(hf, "_parquet_available", lambda: True)
    files = {
        "dataset_infos.json": b'{"default": {"description": "not data"}}',
        "data/train-00000-of-00001.parquet": b"parquet-bytes",
    }
    with patch.object(
        hf,
        "_parse_rows",
        side_effect=lambda filename, raw: [{"question": "Q1?", "answer": "A1"}],
    ) as parse_rows:
        _, items, _ = _saved(files)

    assert [i["question"] for i in items] == ["Q1?"]
    parse_rows.assert_called_once_with(
        "data/train-00000-of-00001.parquet", b"parquet-bytes"
    )


def test_pick_data_files_excludes_known_metadata_filenames(monkeypatch):
    """Unit-level check on the picker itself, including a non-root path."""
    monkeypatch.setattr(hf, "_parquet_available", lambda: True)
    files = [
        "dataset_infos.json",
        "some/dir/dataset_dict.json",
        "data/train-00000-of-00001.parquet",
    ]
    assert hf._pick_data_files(files) == ["data/train-00000-of-00001.parquet"]


def test_import_uses_the_explicit_local_dataset_name(token):
    result, _, save = _saved(
        {"train.jsonl": _jsonl({"question": "Q1?", "answer": "A1"})},
        dataset_name="renamed",
    )
    assert result["dataset_name"] == "renamed"
    assert save.call_args.args[0] == OWNER  # imported into the caller's own space
    assert save.call_args.args[1] == "renamed"


def test_import_replaces_foreign_ids_with_a_content_hash(token):
    """Pair ids are global primary keys — a foreign "0" would collide."""
    raw = _jsonl({"id": 0, "question": "Q1?", "answer": "A1", "context": "C1"})
    _, items, _ = _saved({"train.jsonl": raw})
    assert items[0]["id"] == hf._import_pair_id(
        "my-ds", "Q1?", "A1", "C1", "huggingface://kevin/my-ds"
    )


def test_import_keeps_rows_with_the_same_question_and_context_but_different_answers(
    token,
):
    """The fallback id must hash the answer too — most Hub rows have no real
    per-row source_url, so two such rows would otherwise collide on the same
    fallback id (question+context+constant source) and one would silently
    overwrite the other."""
    raw = _jsonl(
        {"question": "Q1?", "answer": "Answer A", "context": "C1"},
        {"question": "Q1?", "answer": "Answer B", "context": "C1"},
    )
    _, items, _ = _saved({"train.jsonl": raw})

    assert len(items) == 2
    ids = {i["id"] for i in items}
    assert len(ids) == 2
    assert {i["answer"] for i in items} == {"Answer A", "Answer B"}


def test_import_ids_differ_across_local_dataset_names_for_the_same_repo(token):
    """Importing the same repo under two different local dataset names must
    not produce the same fallback ids — otherwise save_generation's global
    (dataset-unscoped) id lookup would move the second import's pairs onto the
    first dataset instead of copying them."""
    raw = _jsonl({"question": "Q1?", "answer": "A1", "context": "C1"})

    _, items_a, _ = _saved({"train.jsonl": raw}, dataset_name="dataset-a")
    _, items_b, _ = _saved({"train.jsonl": raw}, dataset_name="dataset-b")

    assert items_a[0]["id"] != items_b[0]["id"]


def test_import_maps_instruction_tuning_rows(token):
    raw = _jsonl(
        {"instruction": "Summarize this.", "input": "Long text.", "output": "Short."}
    )
    _, items, _ = _saved({"train.jsonl": raw})
    assert items[0]["question"] == "Summarize this."
    assert items[0]["answer"] == "Short."
    assert items[0]["context"] == "Long text."


def test_import_maps_chat_transcripts(token):
    raw = _jsonl(
        {
            "messages": [
                {"role": "system", "content": "Be brief."},
                {"role": "user", "content": "Capital of France?"},
                {"role": "assistant", "content": "Paris."},
            ]
        }
    )
    _, items, _ = _saved({"train.jsonl": raw})
    assert (items[0]["question"], items[0]["answer"]) == (
        "Capital of France?",
        "Paris.",
    )


def test_import_reads_csv_and_json_arrays(token):
    _, items, _ = _saved({"data.csv": b"prompt,response\nQ1?,A1\n"})
    assert (items[0]["question"], items[0]["answer"]) == ("Q1?", "A1")

    raw = json.dumps({"data": [{"question": "Q2?", "answer": "A2"}]}).encode()
    _, items, _ = _saved({"data.json": raw})
    assert items[0]["question"] == "Q2?"


def test_import_reads_every_split_and_merges_duplicates(token):
    row = {"question": "Q1?", "answer": "A1"}
    _, items, _ = _saved(
        {
            "data/train.jsonl": _jsonl(row, {"question": "Q2?", "answer": "A2"}),
            "data/test.jsonl": _jsonl(row),
        }
    )
    assert sorted(i["question"] for i in items) == ["Q1?", "Q2?"]


def test_import_without_a_readable_file_lists_the_repo(token, monkeypatch):
    monkeypatch.setattr(hf, "_parquet_available", lambda: False)
    listing, download = _hub({"README.md": b"", "data/train-00000.parquet": b""})
    with listing, download:
        with pytest.raises(ValueError, match="pyarrow") as exc:
            import_dataset_from_hub(OWNER, CREDS, "kevin/my-ds")
    assert "data/train-00000.parquet" in str(exc.value)


def test_import_with_no_mappable_row_lists_the_columns(token):
    listing, download = _hub({"train.jsonl": _jsonl({"text": "free-form"})})
    with listing, download:
        with pytest.raises(ValueError, match="columns found: text"):
            import_dataset_from_hub(OWNER, CREDS, "kevin/my-ds")


def test_import_propagates_a_missing_repo(token):
    with patch.object(
        hf,
        "_list_repo_files",
        side_effect=ValueError("Hugging Face dataset repo 'kevin/nope' not found"),
    ):
        with pytest.raises(ValueError, match="not found"):
            import_dataset_from_hub(OWNER, CREDS, "kevin/nope")
