"""Tests for the Hub viewer (services/hub.py).

The Hub is never contacted: :class:`FakeHub` holds repos as lists of commits
(each a dict of file bytes), knows which token may read which repo, and records
every download, which is what the cache and access assertions are about.
"""

import io
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from huggingface_hub.errors import (
    HfHubHTTPError,
    RepositoryNotFoundError,
    RevisionNotFoundError,
)

from server.core.config import config
from server.services import hub
from server.services.huggingface import HuggingFaceNotConfiguredError
from server.tests.creds import NONE, make_creds

ALICE = make_creds(hf_token="hf_alice")
BOB = make_creds(hf_token="hf_bob")


def _response(status: int) -> httpx.Response:
    return httpx.Response(
        status, request=httpx.Request("GET", "https://huggingface.co/api")
    )


def jsonl(*rows) -> bytes:
    return ("\n".join(json.dumps(r) for r in rows) + "\n").encode("utf-8")


def parquet(rows) -> bytes:
    buffer = io.BytesIO()
    pq.write_table(pa.Table.from_pylist(rows), buffer)
    return buffer.getvalue()


class FakeCardData:
    def __init__(self, **fields):
        self._fields = fields

    def to_dict(self):
        return dict(self._fields)


class FakeHub:
    """Repos → commits (oldest first) → files. ``readers`` are the tokens
    allowed to read a repo, like the Hub does for a private one."""

    def __init__(self):
        self.repos = {}
        self.downloads = []
        self.info_calls = []
        self.fail_info = None

    def add_commit(
        self, repo_id, files, *, readers=("hf_alice",), card=None, title="Update"
    ):
        repo = self.repos.setdefault(repo_id, {"readers": set(readers), "commits": []})
        sha = f"{len(repo['commits']) + 1:040d}"
        repo["commits"].append(
            {
                "sha": sha,
                "files": dict(files),
                "card": card,
                "title": title,
                "created_at": datetime(
                    2026, 1, len(repo["commits"]) + 1, tzinfo=timezone.utc
                ),
            }
        )
        return sha

    def commit(self, token, repo_id, revision):
        repo = self.repos.get(repo_id)
        if repo is None or token not in repo["readers"]:
            raise RepositoryNotFoundError(
                "Repository Not Found", response=_response(404)
            )
        if revision in (None, "main"):
            return repo["commits"][-1]
        for commit in repo["commits"]:
            if commit["sha"] == revision:
                return commit
        raise RevisionNotFoundError("Invalid rev id", response=_response(404))

    def api(self, creds):
        return FakeApi(self, creds.secret("hf_token"))

    def hf_hub_download(
        self, *, repo_id, filename, repo_type, revision, token, cache_dir
    ):
        assert repo_type == "dataset"
        commit = self.commit(token, repo_id, revision)
        self.downloads.append((token, repo_id, revision, filename))
        path = f"{cache_dir}/{len(self.downloads)}-{filename.replace('/', '_')}"
        with open(path, "wb") as f:
            f.write(commit["files"][filename])
        return path


class FakeApi:
    def __init__(self, hub_, token):
        self.hub = hub_
        self.token = token

    def whoami(self, cache=False):
        return {"name": "kevin", "orgs": [{"name": "kevin-org"}]}

    def dataset_info(self, repo_id, *, revision=None, files_metadata=False):
        self.hub.info_calls.append((self.token, repo_id, revision))
        if self.hub.fail_info is not None:
            raise self.hub.fail_info
        commit = self.hub.commit(self.token, repo_id, revision)
        return SimpleNamespace(
            id=repo_id,
            sha=commit["sha"],
            private=True,
            author=repo_id.split("/")[0],
            siblings=[
                SimpleNamespace(rfilename=path, size=len(data), lfs=None)
                for path, data in commit["files"].items()
            ],
            card_data=commit["card"],
            tags=["synthetic"],
            downloads=3,
            likes=1,
            last_modified=commit["created_at"],
        )

    def list_repo_refs(self, repo_id, repo_type):
        commit = self.hub.commit(self.token, repo_id, None)
        return SimpleNamespace(
            branches=[SimpleNamespace(name="main", target_commit=commit["sha"])],
            tags=[],
        )

    def list_repo_commits(self, repo_id, repo_type):
        self.hub.commit(self.token, repo_id, None)
        return [
            SimpleNamespace(
                commit_id=c["sha"],
                title=c["title"],
                message="",
                authors=["kevin"],
                created_at=c["created_at"],
            )
            for c in reversed(self.hub.repos[repo_id]["commits"])
        ]


@pytest.fixture
def fake(monkeypatch):
    hub.clear_caches()
    fake_hub = FakeHub()
    monkeypatch.setattr(hub, "_api", fake_hub.api)
    monkeypatch.setattr("huggingface_hub.hf_hub_download", fake_hub.hf_hub_download)
    yield fake_hub
    hub.clear_caches()


QA_ROWS = [
    {
        "id": "a",
        "question": "What is Alpha?",
        "answer": "A tool.",
        "category": "repo",
        "repo": "alpha",
        "confidence": 0.9,
    },
    {
        "id": "b",
        "question": "What is Beta?",
        "answer": "A library.",
        "category": "docs",
        "repo": "beta",
        "confidence": 0.4,
    },
    {
        "id": "c",
        "question": "what is alpha? ",
        "answer": "Again.",
        "category": "repo",
        "repo": "alpha",
        "confidence": 0.7,
    },
    {
        "id": "d",
        "question": "Who is Kevin?",
        "answer": "A developer.",
        "category": "profile",
        "repo": None,
        "confidence": 1.0,
    },
]


def _qa_repo(fake, repo_id="kevin/qa", rows=QA_ROWS, **kwargs):
    return fake.add_commit(
        repo_id,
        {
            "README.md": b"---\nlanguage:\n- en\n---\n\n# QA\n\nPairs.\n",
            "train.jsonl": jsonl(*rows),
            "review.jsonl": jsonl(
                {"id": "r", "question": "Held out?", "answer": "Yes."}
            ),
            "manifest.json": b'{"sources": {}}',
        },
        **kwargs,
    )


# --- repo ids --------------------------------------------------------------------


@pytest.mark.parametrize(
    "owner,name", [("kevin", "qa"), ("my-org", "ds.v2"), ("a", "b_c")]
)
def test_repo_id_accepts_hub_names(owner, name):
    assert hub.repo_id_of(owner, name) == f"{owner}/{name}"


@pytest.mark.parametrize(
    "owner,name", [("..", "x"), ("kevin", ".hidden"), ("a--b", "x"), ("kevin", "a b")]
)
def test_repo_id_refuses_anything_else(owner, name):
    with pytest.raises(hub.HubNotFoundError):
        hub.repo_id_of(owner, name)


# --- listing ---------------------------------------------------------------------


class ListingApi:
    def __init__(self, datasets):
        self.datasets = datasets
        self.calls = []

    def whoami(self, cache=False):
        return {"name": "kevin", "orgs": [{"name": "kevin-org"}]}

    def list_datasets(self, **kwargs):
        self.calls.append(kwargs)
        return iter(self.datasets)


def _info(repo_id, **fields):
    defaults = dict(
        id=repo_id,
        private=False,
        downloads=0,
        likes=0,
        tags=None,
        siblings=None,
        card_data=None,
        gated=False,
    )
    defaults.update(fields)
    return SimpleNamespace(**defaults)


def test_list_needs_a_token():
    with pytest.raises(HuggingFaceNotConfiguredError, match="Settings"):
        hub.list_datasets(NONE)


def test_list_defaults_to_the_token_account_and_offers_its_orgs(monkeypatch):
    api = ListingApi([_info("kevin/a"), _info("kevin/b", private=True)])
    monkeypatch.setattr(hub, "_api", lambda creds: api)

    result = hub.list_datasets(ALICE)

    assert result["namespace"] == "kevin"
    assert result["namespaces"] == ["kevin", "kevin-org"]
    assert [d["id"] for d in result["datasets"]] == ["kevin/a", "kevin/b"]
    assert result["datasets"][1]["private"] is True
    assert result["datasets"][0]["url"] == "https://huggingface.co/datasets/kevin/a"
    # Everything the Hub knows, newest first.
    assert api.calls == [{"author": "kevin", "sort": "last_modified", "full": True}]


def test_list_starts_on_the_saved_namespace(monkeypatch):
    api = ListingApi([])
    monkeypatch.setattr(hub, "_api", lambda creds: api)

    result = hub.list_datasets(make_creds(hf_token="hf_alice", hf_namespace="team"))

    assert result["namespace"] == "team"
    assert result["namespaces"] == ["team", "kevin", "kevin-org"]
    assert api.calls[0]["author"] == "team"


def test_list_another_namespace_of_yours(monkeypatch):
    api = ListingApi([])
    monkeypatch.setattr(hub, "_api", lambda creds: api)

    assert hub.list_datasets(ALICE, author="kevin-org")["namespace"] == "kevin-org"


def test_list_refuses_a_namespace_that_is_not_yours(monkeypatch):
    monkeypatch.setattr(hub, "_api", lambda creds: ListingApi([]))

    with pytest.raises(hub.HubNotFoundError):
        hub.list_datasets(ALICE, author="someone-else")


def test_list_surfaces_the_hub_metadata(monkeypatch):
    created = datetime(2026, 1, 2, tzinfo=timezone.utc)
    info = _info(
        "kevin/a",
        author="kevin",
        downloads=42,
        downloads_all_time=1000,
        likes=7,
        gated="auto",
        tags=["synthetic"],
        description="Docs Q/A.",
        siblings=[SimpleNamespace(rfilename="README.md")],
        used_storage=123,
        sha="abc",
        created_at=created,
        last_modified=created,
        card_data=FakeCardData(
            pretty_name="Docs QA",
            language=["fr"],
            license=["mit", "cc-by-4.0"],
            size_categories=["n<1K"],
        ),
    )
    monkeypatch.setattr(hub, "_api", lambda creds: ListingApi([info]))

    row = hub.list_datasets(ALICE)["datasets"][0]

    assert row["downloads"] == 42 and row["likes"] == 7 and row["gated"] == "auto"
    assert row["file_count"] == 1 and row["used_storage"] == 123 and row["sha"] == "abc"
    assert row["created_at"] == created.isoformat()
    assert row["pretty_name"] == "Docs QA" and row["language"] == ["fr"]
    # A list-valued license is flattened: the schema types it as a string.
    assert row["license"] == "mit, cc-by-4.0"
    assert row["size_category"] == "n<1K"


def test_list_handles_a_repo_without_card(monkeypatch):
    monkeypatch.setattr(hub, "_api", lambda creds: ListingApi([_info("kevin/a")]))

    row = hub.list_datasets(ALICE)["datasets"][0]

    assert row["pretty_name"] is None and row["license"] is None
    assert row["file_count"] is None and row["tags"] == [] and row["gated"] is False


# --- configs and splits -------------------------------------------------------------


def _snapshot(paths, card=None):
    return hub.Snapshot(
        repo_id="kevin/x",
        sha="1" * 40,
        info=SimpleNamespace(card_data=card),
        files=tuple(hub.HubFile(path=p, size=1, lfs=False) for p in paths),
    )


def _names(views):
    return [(v.config, v.split, list(v.files), v.extra) for v in views]


def test_splits_follow_file_names_and_extras_stay_visible():
    views = hub.views(
        _snapshot(
            [
                "README.md",
                "train.jsonl",
                "review.jsonl",
                "manifest.json",
                ".gitattributes",
            ]
        )
    )

    assert _names(views) == [
        ("default", "train", ["train.jsonl"], False),
        # The app's held-out pairs: no split keyword, still one click away.
        ("default", "review", ["review.jsonl"], True),
    ]


def test_split_keywords_are_whole_words():
    views = hub.views(
        _snapshot(
            [
                "data/train-00000-of-00002.parquet",
                "data/train-00001-of-00002.parquet",
                "data/test.parquet",
                "data/latest.csv",
            ]
        )
    )

    assert _names(views)[:2] == [
        (
            "default",
            "train",
            ["data/train-00000-of-00002.parquet", "data/train-00001-of-00002.parquet"],
            False,
        ),
        ("default", "test", ["data/test.parquet"], False),
    ]
    # "latest" is not "test".
    assert ("default", "latest", ["data/latest.csv"], True) in _names(views)


def test_without_split_names_the_main_format_is_the_train_split():
    views = hub.views(_snapshot(["a.jsonl", "b.jsonl", "c.csv"]))

    assert _names(views) == [
        ("default", "train", ["a.jsonl", "b.jsonl"], False),
        ("default", "c", ["c.csv"], True),
    ]


def test_card_configs_declare_the_tables():
    card = FakeCardData(
        configs=[
            {
                "config_name": "profile",
                "data_files": [{"split": "train", "path": "data/profile.jsonl"}],
            },
            {
                "config_name": "github",
                "default": True,
                "data_files": [{"split": "train", "path": ["data/github.jsonl"]}],
            },
        ]
    )
    views = hub.views(
        _snapshot(["data/profile.jsonl", "data/github.jsonl", "manifest.json"], card)
    )

    # The default config comes first.
    assert _names(views) == [
        ("github", "train", ["data/github.jsonl"], False),
        ("profile", "train", ["data/profile.jsonl"], False),
    ]


def test_a_plain_data_files_string_is_the_train_split():
    card = FakeCardData(
        configs=[{"config_name": "default", "data_files": "data/train.jsonl"}]
    )

    assert _names(hub.views(_snapshot(["data/train.jsonl"], card))) == [
        ("default", "train", ["data/train.jsonl"], False)
    ]


def test_double_star_globs_match_root_files():
    card = FakeCardData(
        configs=[
            {
                "config_name": "default",
                "data_files": [{"split": "test", "path": "**/*.csv"}],
            }
        ]
    )

    assert _names(hub.views(_snapshot(["x.csv", "d/y.csv"], card))) == [
        ("default", "test", ["d/y.csv", "x.csv"], False)
    ]


def test_find_view_reports_an_unknown_split():
    with pytest.raises(hub.HubNotFoundError):
        hub.find_view(_snapshot(["train.jsonl"]), None, "nope")


# --- rows -----------------------------------------------------------------------------------


def test_rows_pages_through_a_split(fake):
    _qa_repo(fake)

    page = hub.rows(ALICE, "kevin/qa", offset=1, length=2)

    assert page["sha"] == "1".zfill(40)
    assert (page["config"], page["split"]) == ("default", "train")
    assert page["num_rows_total"] == 4 and page["num_rows_matched"] == 4
    assert [r["row_idx"] for r in page["rows"]] == [1, 2]
    assert page["rows"][0]["row"]["question"] == "What is Beta?"
    assert hub.ROW_IDX not in page["rows"][0]["row"]
    assert {f["name"]: f["kind"] for f in page["features"]}["confidence"] == "number"
    assert page["qa"] == {"question": "question", "answer": "answer", "context": None}


def test_rows_search_filter_and_sort(fake):
    _qa_repo(fake)

    page = hub.rows(
        ALICE,
        "kevin/qa",
        query="ALPHA",
        filters=[hub.RowFilter("confidence", "gte", 0.5)],
        sort="confidence",
        order="desc",
    )

    assert [r["row"]["id"] for r in page["rows"]] == ["a", "c"]
    # Positions are the published ones, whatever the order shown.
    assert [r["row_idx"] for r in page["rows"]] == [0, 2]
    assert page["num_rows_matched"] == 2 and page["num_rows_total"] == 4


def test_rows_refuse_unknown_columns(fake):
    _qa_repo(fake)

    with pytest.raises(hub.HubBadQueryError):
        hub.rows(ALICE, "kevin/qa", filters=[hub.RowFilter("nope", "eq", "x")])
    with pytest.raises(hub.HubBadQueryError):
        hub.rows(ALICE, "kevin/qa", sort="nope")


def test_extra_files_are_readable(fake):
    _qa_repo(fake)

    page = hub.rows(ALICE, "kevin/qa", split="review")

    assert [r["row"]["id"] for r in page["rows"]] == ["r"]


def test_long_cells_are_cut_and_the_full_row_is_one_call_away(fake):
    long_answer = "x" * (hub.MAX_CELL_CHARS + 10)
    _qa_repo(fake, rows=[{"id": "a", "question": "Q?", "answer": long_answer}])

    listed = hub.rows(ALICE, "kevin/qa")["rows"][0]
    full = hub.row(ALICE, "kevin/qa", 0)

    assert listed["truncated_cells"] == ["answer"]
    assert len(listed["row"]["answer"]) == hub.MAX_CELL_CHARS
    assert full["row"]["answer"] == long_answer


def test_row_out_of_range_is_not_found(fake):
    _qa_repo(fake)

    with pytest.raises(hub.HubNotFoundError):
        hub.row(ALICE, "kevin/qa", 99)


@pytest.mark.parametrize(
    "path,data",
    [
        ("train.csv", b"question,answer\nQ1?,A1\nQ2?,A2\n"),
        (
            "train.json",
            json.dumps(
                [
                    {"question": "Q1?", "answer": "A1"},
                    {"question": "Q2?", "answer": "A2"},
                ]
            ).encode(),
        ),
        (
            "train.json",
            json.dumps(
                {
                    "data": [
                        {"question": "Q1?", "answer": "A1"},
                        {"question": "Q2?", "answer": "A2"},
                    ]
                }
            ).encode(),
        ),
        (
            "train.parquet",
            parquet(
                [
                    {"question": "Q1?", "answer": "A1"},
                    {"question": "Q2?", "answer": "A2"},
                ]
            ),
        ),
    ],
)
def test_every_supported_format_reads(fake, path, data):
    fake.add_commit("kevin/f", {path: data})

    page = hub.rows(ALICE, "kevin/f")

    assert [r["row"]["question"] for r in page["rows"]] == ["Q1?", "Q2?"]


def test_a_column_of_mixed_types_is_kept_as_text(fake):
    fake.add_commit(
        "kevin/m", {"train.jsonl": jsonl({"v": 1}, {"v": "one"}, {"v": {"n": 1}})}
    )

    values = [r["row"]["v"] for r in hub.rows(ALICE, "kevin/m")["rows"]]

    assert values == ["1", "one", '{"n": 1}']


def test_unreadable_data_is_reported(fake):
    fake.add_commit("kevin/bad", {"train.jsonl": b"{not json\n"})

    with pytest.raises(hub.HubUnreadableError):
        hub.rows(ALICE, "kevin/bad")


def test_a_split_above_the_limit_is_refused_before_any_download(fake, monkeypatch):
    _qa_repo(fake)
    monkeypatch.setattr(config, "max_hub_view_bytes", 10)

    with pytest.raises(hub.HubTooLargeError, match="Hugging Face"):
        hub.rows(ALICE, "kevin/qa")
    assert fake.downloads == []


# --- caching and access ------------------------------------------------------------------------------


def test_a_split_is_downloaded_once_per_commit(fake, monkeypatch):
    # Every call asks the Hub again (no resolution reuse)...
    monkeypatch.setattr(config, "hub_resolve_ttl_seconds", 0.0)
    _qa_repo(fake)

    hub.rows(ALICE, "kevin/qa")
    hub.rows(ALICE, "kevin/qa", query="beta")
    hub.statistics(ALICE, "kevin/qa")

    # ...but the table of a commit is downloaded once.
    assert len(fake.info_calls) == 3
    assert [d[3] for d in fake.downloads] == ["train.jsonl"]

    # A new commit on the branch is a new table.
    _qa_repo(fake, rows=QA_ROWS[:1])
    assert hub.rows(ALICE, "kevin/qa")["num_rows_total"] == 1
    assert [d[3] for d in fake.downloads] == ["train.jsonl", "train.jsonl"]


def test_a_resolution_is_reused_briefly_per_token(fake):
    _qa_repo(fake)

    hub.rows(ALICE, "kevin/qa")
    hub.statistics(ALICE, "kevin/qa")

    assert fake.info_calls == [("hf_alice", "kevin/qa", None)]


def test_a_cached_split_is_never_served_to_a_token_the_hub_refuses(fake):
    """Alice loads her private dataset; Bob, whose token can't read it, gets
    "not found" — not Alice's cached rows."""
    _qa_repo(fake, readers=("hf_alice",))
    hub.rows(ALICE, "kevin/qa")

    with pytest.raises(hub.HubNotFoundError):
        hub.rows(BOB, "kevin/qa")
    with pytest.raises(hub.HubNotFoundError):
        hub.statistics(BOB, "kevin/qa")
    with pytest.raises(hub.HubNotFoundError):
        hub.row(BOB, "kevin/qa", 0)
    with pytest.raises(hub.HubNotFoundError):
        hub.overview(BOB, "kevin/qa")
    # Bob's attempts were checked with Bob's token, never answered from cache.
    assert ("hf_bob", "kevin/qa", None) in fake.info_calls
    assert all(token == "hf_alice" for token, *_ in fake.downloads)


def test_an_older_revision_shows_its_own_rows(fake):
    first = _qa_repo(fake)
    _qa_repo(fake, rows=QA_ROWS[:2])

    old = hub.rows(ALICE, "kevin/qa", revision=first)
    new = hub.rows(ALICE, "kevin/qa", revision="2".zfill(40))

    assert old["sha"] == first and old["num_rows_total"] == 4
    assert new["num_rows_total"] == 2


def test_an_unknown_revision_is_not_found(fake):
    _qa_repo(fake)

    with pytest.raises(hub.HubNotFoundError, match="revision"):
        hub.rows(ALICE, "kevin/qa", revision="f" * 40)


def test_a_failing_hub_is_unavailable_not_missing(fake):
    _qa_repo(fake)
    fake.fail_info = HfHubHTTPError("Internal Server Error", response=_response(500))

    with pytest.raises(hub.HubUnavailableError):
        hub.rows(ALICE, "kevin/qa")


# --- statistics --------------------------------------------------------------------------------------


def test_statistics_profile_every_column(fake):
    _qa_repo(fake)

    stats = hub.statistics(ALICE, "kevin/qa")
    columns = {c["name"]: c for c in stats["columns"]}

    assert stats["num_rows"] == 4 and stats["num_columns"] == 6
    assert columns["category"]["categories"]["values"][0] == {
        "value": "repo",
        "count": 2,
    }
    assert columns["question"]["categories"] is None  # every value differs
    assert columns["question"]["lengths"]["min"] == len("Who is Kevin?")
    assert columns["confidence"]["number"]["max"] == 1.0
    assert sum(b["count"] for b in columns["confidence"]["number"]["histogram"]) == 4
    assert columns["repo"]["null_count"] == 1
    assert stats["qa"]["question"] == "question"
    # "What is Alpha?" and "what is alpha? " are the same question.
    assert stats["duplicates"] == {"column": "question", "duplicate_rows": 1}


# --- overview and history ------------------------------------------------------------------------------


def test_overview_reads_the_card_files_and_tables_at_one_commit(fake):
    sha = _qa_repo(fake)

    detail = hub.overview(ALICE, "kevin/qa")

    assert detail["sha"] == sha
    assert detail["card"]["markdown"] == "# QA\n\nPairs.\n"
    assert {f["path"] for f in detail["files"]} >= {"README.md", "train.jsonl"}
    assert [(v["split"], v["extra"]) for v in detail["views"]] == [
        ("train", False),
        ("review", True),
    ]
    assert detail["views"][0]["num_bytes"] == len(jsonl(*QA_ROWS))
    assert detail["refs"]["branches"] == [{"name": "main", "target_commit": sha}]
    assert detail["max_view_bytes"] == config.max_hub_view_bytes


def test_commits_are_versions_newest_first(fake):
    first = _qa_repo(fake, title="v1")
    second = _qa_repo(fake, title="v2")

    history = hub.commits(ALICE, "kevin/qa")

    assert [c["id"] for c in history["commits"]] == [second, first]
    assert history["commits"][0]["title"] == "v2"
    assert history["commits"][0]["created_at"].startswith("2026-01-02")


def test_compare_matches_rows_by_id(fake):
    first = _qa_repo(fake)
    edited = (
        [dict(QA_ROWS[0], answer="A better tool.")]
        + QA_ROWS[1:3]
        + [
            {
                "id": "e",
                "question": "New?",
                "answer": "Yes.",
                "category": "docs",
                "repo": "beta",
                "confidence": 0.5,
            }
        ]
    )
    second = _qa_repo(fake, rows=edited)

    diff = hub.compare(ALICE, "kevin/qa", base=first, head=second)

    assert diff["key"] == "id"
    assert (diff["added"], diff["removed"], diff["changed"], diff["unchanged"]) == (
        1,
        1,
        1,
        2,
    )
    assert diff["added_examples"][0]["id"] == "e"
    assert diff["removed_examples"][0]["id"] == "d"
    assert diff["changed_examples"][0]["after"]["answer"] == "A better tool."


def test_compare_without_ids_matches_by_content(fake):
    first = fake.add_commit("kevin/c", {"train.jsonl": jsonl({"q": "1"}, {"q": "2"})})
    second = fake.add_commit("kevin/c", {"train.jsonl": jsonl({"q": "2"}, {"q": "3"})})

    diff = hub.compare(ALICE, "kevin/c", base=first, head=second)

    assert diff["key"] == "content"
    assert (diff["added"], diff["removed"], diff["changed"]) == (1, 1, 0)


def test_compare_with_a_split_added_later_counts_everything_as_new(fake):
    first = fake.add_commit("kevin/s", {"train.jsonl": jsonl({"id": "a"})})
    second = fake.add_commit(
        "kevin/s",
        {
            "train.jsonl": jsonl({"id": "a"}),
            "test.jsonl": jsonl({"id": "t1"}, {"id": "t2"}),
        },
    )

    diff = hub.compare(ALICE, "kevin/s", base=first, head=second, split="test")

    assert (diff["added"], diff["removed"], diff["base_rows"]) == (2, 0, 0)
