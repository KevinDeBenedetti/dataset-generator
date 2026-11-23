"""The Hub dataset repo: open, read a dataset version, publish the next.

Everything goes through the module's interface against the in-memory Hub
(tests/fake_hub.py). Only the last section touches ``HfHubBackend``, with a
stand-in ``HfApi``, to pin how the real Hub's answers are translated.
"""

import json
from types import SimpleNamespace

import httpx
import pytest
from huggingface_hub.errors import HfHubHTTPError, RepositoryNotFoundError

from server.core.config import config
from server.services import hub_repo
from server.services.hub_repo import (
    APP_CARD_TAG,
    CARD_PATH,
    DATA_PAIRS_PATH,
    MANIFEST_PATH,
    REVIEW_PATH,
    ROOT_PAIRS_PATH,
    DatasetMoved,
    DatasetTooLarge,
    DatasetUnreadable,
    HfHubBackend,
    HubTokenMissing,
    HubTokenRejected,
    RepoNotPrivate,
    is_app_card,
    mark_app_card,
    open_repo,
    to_jsonl,
)
from server.tests.creds import NONE, make_creds
from server.tests.fake_hub import InMemoryHub

CREDS = make_creds(hf_token="hf_test_token")
REPO = "kevin/notes"
CARD = "---\nlanguage:\n- en\n---\n\n# Notes\n"
FOREIGN_CARD = "---\nlicense: mit\n---\n\n# Written by hand\n"


def row(n: int, **extra) -> dict:
    return {
        "id": f"id-{n}",
        "question": f"Question {n}?",
        "answer": f"Answer {n}.",
        **extra,
    }


def opened(hub: InMemoryHub, repo_id: str = REPO, **kwargs):
    return open_repo(CREDS, repo_id, backend=hub, **kwargs)


def rows_at(hub: InMemoryHub, path: str, repo_id: str = REPO) -> list:
    raw = hub.files(repo_id)[path].decode("utf-8")
    return [json.loads(line) for line in raw.splitlines()]


# --- open --------------------------------------------------------------------


def test_open_needs_a_token():
    with pytest.raises(HubTokenMissing, match="Settings"):
        open_repo(NONE, REPO, backend=InMemoryHub())


def test_open_fails_on_a_token_the_hub_refuses():
    with pytest.raises(HubTokenRejected):
        opened(InMemoryHub(rejects_token=True))


def test_open_creates_nothing():
    hub = InMemoryHub()
    opened(hub)
    assert not hub.exists(REPO)


def test_open_keeps_a_full_repo_id():
    assert opened(InMemoryHub(account="someone"), " org/data ").repo_id == "org/data"


def test_open_completes_a_bare_name_with_the_saved_namespace():
    creds = make_creds(hf_token="hf_test_token", hf_namespace="my-org")
    repo = open_repo(creds, "github-qa", backend=InMemoryHub(account="kevin"))
    assert repo.repo_id == "my-org/github-qa"


def test_open_completes_a_bare_name_with_the_tokens_account():
    assert (
        opened(InMemoryHub(account="kevin"), "github-qa").repo_id == "kevin/github-qa"
    )


def test_open_refuses_a_bare_name_without_any_namespace():
    with pytest.raises(HubTokenRejected, match="namespace"):
        opened(InMemoryHub(account=None), "github-qa")


# --- read --------------------------------------------------------------------


def test_a_repo_that_does_not_exist_reads_as_an_empty_version():
    version = opened(InMemoryHub()).read()
    assert version.commit is None
    assert version.rows == [] and version.review == [] and version.manifest is None
    assert version.pairs_path == DATA_PAIRS_PATH
    assert version.app_card is True


def test_a_new_repo_takes_the_layout_its_caller_asks_for():
    version = opened(InMemoryHub(), new_pairs_path=ROOT_PAIRS_PATH).read()
    assert version.pairs_path == ROOT_PAIRS_PATH


def test_read_returns_a_job_dataset_whole_at_one_commit():
    hub = InMemoryHub()
    commit = hub.push(
        REPO,
        {
            ROOT_PAIRS_PATH: to_jsonl([row(1, category="projects"), row(2)]),
            REVIEW_PATH: to_jsonl([row(3)]),
            MANIFEST_PATH: b'{"sources": {"a": "h1"}}',
            CARD_PATH: CARD.encode(),
        },
    )
    version = opened(hub).read()
    assert version.commit == commit
    assert version.pairs_path == ROOT_PAIRS_PATH
    assert version.rows == [row(1, category="projects"), row(2)]
    assert version.review == [row(3)]
    assert version.manifest == {"sources": {"a": "h1"}}
    assert version.card == CARD
    assert version.url == "https://huggingface.co/datasets/kevin/notes"


def test_read_finds_a_draft_dataset_in_its_own_layout():
    hub = InMemoryHub()
    hub.push(REPO, {DATA_PAIRS_PATH: to_jsonl([row(1)])})
    version = opened(hub, new_pairs_path=ROOT_PAIRS_PATH).read()
    assert version.pairs_path == DATA_PAIRS_PATH
    assert version.rows == [row(1)]


def test_read_keeps_rows_exactly_as_stored():
    odd = {"prompt": "no id, no question", "nested": {"a": [1, 2]}, "text": "é"}
    hub = InMemoryHub()
    hub.push(REPO, {ROOT_PAIRS_PATH: to_jsonl([odd])})
    assert opened(hub).read().rows == [odd]


def test_an_existing_repo_without_rows_reads_as_empty():
    hub = InMemoryHub()
    hub.push(REPO, {".gitattributes": b""})
    version = opened(hub).read()
    assert version.commit is not None and version.rows == []


@pytest.mark.parametrize(
    "content", [b'{"id": 1}\nnot json\n', b'{"id": 1}\n[1, 2]\n', b"\xff\xfe"]
)
def test_a_rows_file_that_is_not_json_lines_stops_the_read(content):
    hub = InMemoryHub()
    hub.push(REPO, {ROOT_PAIRS_PATH: content})
    with pytest.raises(DatasetUnreadable, match="train.jsonl"):
        opened(hub).read()


@pytest.mark.parametrize("content", [b"{broken", b"[1, 2]"])
def test_a_manifest_that_is_not_a_json_object_stops_the_read(content):
    hub = InMemoryHub()
    hub.push(REPO, {ROOT_PAIRS_PATH: to_jsonl([row(1)]), MANIFEST_PATH: content})
    with pytest.raises(DatasetUnreadable, match="manifest.json"):
        opened(hub).read()


def test_a_dataset_over_the_cap_is_refused_before_any_download(monkeypatch):
    hub = InMemoryHub()
    hub.push(
        REPO,
        {ROOT_PAIRS_PATH: to_jsonl([row(1)]), REVIEW_PATH: to_jsonl([row(2)])},
    )
    monkeypatch.setattr(config, "max_hub_import_bytes", 60)
    with pytest.raises(DatasetTooLarge, match="too large"):
        opened(hub).read()
    assert hub.downloads == []


def test_the_cap_ignores_a_layout_the_read_does_not_use(monkeypatch):
    hub = InMemoryHub()
    small = to_jsonl([row(1)])
    hub.push(REPO, {ROOT_PAIRS_PATH: small, DATA_PAIRS_PATH: b"x" * 500})
    monkeypatch.setattr(config, "max_hub_import_bytes", len(small) + 10)
    assert opened(hub).read().rows == [row(1)]
    assert hub.downloads == [ROOT_PAIRS_PATH]


# --- publish -----------------------------------------------------------------


def test_publishing_to_a_new_repo_creates_it_private_in_the_callers_layout():
    hub = InMemoryHub()
    repo = opened(hub)
    published = repo.publish(repo.read(), [row(1)], card=CARD, message="Add 1 pair")
    assert hub.is_private(REPO) is True
    assert rows_at(hub, DATA_PAIRS_PATH) == [row(1)]
    assert hub.log(REPO)[-1] == "Add 1 pair"
    assert set(hub.files(REPO)) == {".gitattributes", DATA_PAIRS_PATH, CARD_PATH}
    assert published == repo.read()


def test_publishing_writes_back_to_the_file_the_repo_already_has():
    hub = InMemoryHub()
    hub.push(REPO, {ROOT_PAIRS_PATH: to_jsonl([row(1)])})
    repo = opened(hub)  # a draft, whose own layout is data/train.jsonl
    base = repo.read()
    repo.publish(base, [*base.rows, row(2)], card=CARD, message="Add data")
    assert rows_at(hub, ROOT_PAIRS_PATH) == [row(1), row(2)]
    assert DATA_PAIRS_PATH not in hub.files(REPO)


def test_a_publication_without_a_manifest_leaves_the_jobs_files_alone():
    hub = InMemoryHub()
    job_files = {REVIEW_PATH: to_jsonl([row(9)]), MANIFEST_PATH: b'{"sources": {}}'}
    hub.push(REPO, {ROOT_PAIRS_PATH: to_jsonl([row(1)]), **job_files})
    repo = opened(hub)
    published = repo.publish(repo.read(), [row(1), row(2)], card=CARD, message="m")
    files = hub.files(REPO)
    assert {p: files[p] for p in job_files} == job_files
    assert published.review == [row(9)] and published.manifest == {"sources": {}}


def test_a_job_publication_writes_rows_review_and_manifest_in_one_commit():
    hub = InMemoryHub()
    repo = opened(hub, new_pairs_path=ROOT_PAIRS_PATH)
    repo.publish(
        repo.read(),
        [row(1)],
        card=CARD,
        message="Export",
        review=[row(2)],
        manifest={"sources": {"a": "h"}},
    )
    assert hub.log(REPO) == ["initial commit", "Export"]
    assert rows_at(hub, ROOT_PAIRS_PATH) == [row(1)]
    assert rows_at(hub, REVIEW_PATH) == [row(2)]
    assert json.loads(hub.files(REPO)[MANIFEST_PATH]) == {"sources": {"a": "h"}}


def test_a_job_publication_empties_a_review_list_that_no_longer_applies():
    hub = InMemoryHub()
    hub.push(
        REPO,
        {
            ROOT_PAIRS_PATH: to_jsonl([row(1)]),
            REVIEW_PATH: to_jsonl([row(2)]),
            MANIFEST_PATH: b"{}",
        },
    )
    repo = opened(hub)
    repo.publish(
        repo.read(), [row(1)], card=CARD, message="m", manifest={"sources": {}}
    )
    assert hub.files(REPO)[REVIEW_PATH] == b""
    assert repo.read().review == []


def test_non_ascii_text_is_stored_readable():
    hub = InMemoryHub()
    repo = opened(hub)
    repo.publish(repo.read(), [row(1, answer="Zoé à Besançon")], card=CARD, message="m")
    assert "Zoé à Besançon" in hub.files(REPO)[DATA_PAIRS_PATH].decode("utf-8")


def test_a_version_of_another_repo_is_refused():
    hub = InMemoryHub()
    other = opened(hub, "kevin/other").read()
    with pytest.raises(ValueError, match="kevin/other"):
        opened(hub).publish(other, [row(1)], card=CARD, message="m")


# --- a moved dataset ---------------------------------------------------------


def test_publishing_on_a_dataset_that_moved_writes_nothing():
    hub = InMemoryHub()
    hub.push(REPO, {ROOT_PAIRS_PATH: to_jsonl([row(1)])})
    repo = opened(hub)
    base = repo.read()
    hub.push(REPO, {ROOT_PAIRS_PATH: to_jsonl([row(1), row(2)])})
    with pytest.raises(DatasetMoved):
        repo.publish(base, [row(1), row(3)], card=CARD, message="stale")
    assert rows_at(hub, ROOT_PAIRS_PATH) == [row(1), row(2)]
    assert "stale" not in hub.log(REPO)


def test_reading_again_after_a_move_lets_the_publication_through():
    hub = InMemoryHub()
    hub.push(REPO, {ROOT_PAIRS_PATH: to_jsonl([row(1)])})
    repo = opened(hub)
    stale = repo.read()
    hub.push(REPO, {ROOT_PAIRS_PATH: to_jsonl([row(1), row(2)])})
    with pytest.raises(DatasetMoved):
        repo.publish(stale, [row(1), row(3)], card=CARD, message="m")
    fresh = repo.read()
    repo.publish(fresh, [*fresh.rows, row(3)], card=CARD, message="m")
    assert rows_at(hub, ROOT_PAIRS_PATH) == [row(1), row(2), row(3)]


def test_a_card_only_edit_on_the_hub_is_a_move_too():
    hub = InMemoryHub()
    hub.push(REPO, {ROOT_PAIRS_PATH: to_jsonl([row(1)])})
    repo = opened(hub)
    base = repo.read()
    hub.push(REPO, {CARD_PATH: FOREIGN_CARD.encode()})
    with pytest.raises(DatasetMoved):
        repo.publish(base, [row(1)], card=CARD, message="m")
    assert hub.files(REPO)[CARD_PATH] == FOREIGN_CARD.encode()


def test_a_repo_filled_by_someone_else_since_it_read_as_missing_has_moved():
    hub = InMemoryHub()
    repo = opened(hub)
    base = repo.read()
    hub.push(REPO, {DATA_PAIRS_PATH: to_jsonl([row(7)])})
    with pytest.raises(DatasetMoved):
        repo.publish(base, [row(1)], card=CARD, message="m")
    assert rows_at(hub, DATA_PAIRS_PATH) == [row(7)]


def test_a_repo_deleted_since_the_read_has_moved():
    hub = InMemoryHub()
    hub.push(REPO, {ROOT_PAIRS_PATH: to_jsonl([row(1)])})
    repo = opened(hub)
    base = repo.read()
    hub.delete(REPO)
    with pytest.raises(DatasetMoved):
        repo.publish(base, [row(1)], card=CARD, message="m")
    assert not hub.exists(REPO)


# --- privacy -----------------------------------------------------------------


@pytest.mark.parametrize(
    "private, word", [(False, "is public"), (None, "unknown visibility")]
)
def test_a_repo_not_confirmed_private_is_never_written_to(private, word):
    hub = InMemoryHub()
    hub.push(REPO, {ROOT_PAIRS_PATH: to_jsonl([row(1)])}, private=private)
    repo = opened(hub)
    base = repo.read()  # reading is allowed
    assert base.rows == [row(1)]
    with pytest.raises(RepoNotPrivate, match=word):
        repo.publish(base, [row(1), row(2)], card=CARD, message="m")
    assert rows_at(hub, ROOT_PAIRS_PATH) == [row(1)]


def test_a_public_repo_made_since_it_read_as_missing_is_refused():
    hub = InMemoryHub()
    repo = opened(hub)
    base = repo.read()
    hub.push(REPO, {".gitattributes": b""}, private=False)
    with pytest.raises(RepoNotPrivate):
        repo.publish(base, [row(1)], card=CARD, message="m")
    assert DATA_PAIRS_PATH not in hub.files(REPO)


# --- cards -------------------------------------------------------------------


def test_the_first_card_is_the_callers_carrying_the_apps_tag():
    hub = InMemoryHub()
    repo = opened(hub)
    repo.publish(repo.read(), [row(1)], card=CARD, message="m")
    card = hub.files(REPO)[CARD_PATH].decode()
    assert card.endswith("# Notes\n") and f"- {APP_CARD_TAG}" in card
    assert repo.read().app_card is True


def test_an_app_card_is_replaced_on_the_next_publication():
    hub = InMemoryHub()
    repo = opened(hub)
    first = repo.publish(repo.read(), [row(1)], card=CARD, message="m")
    repo.publish(
        first, [row(1), row(2)], card=CARD.replace("Notes", "More notes"), message="m"
    )
    assert "# More notes" in hub.files(REPO)[CARD_PATH].decode()


def test_a_card_written_elsewhere_is_left_as_it_is():
    hub = InMemoryHub()
    hub.push(
        REPO, {ROOT_PAIRS_PATH: to_jsonl([row(1)]), CARD_PATH: FOREIGN_CARD.encode()}
    )
    repo = opened(hub)
    base = repo.read()
    assert base.app_card is False
    published = repo.publish(base, [row(1), row(2)], card=CARD, message="m")
    assert hub.files(REPO)[CARD_PATH] == FOREIGN_CARD.encode()
    assert published.card == FOREIGN_CARD and published.app_card is False


def test_a_card_from_before_the_tag_is_still_the_apps():
    legacy = (
        "---\ntags:\n- synthetic\n---\n\n# ds\n\n2 question/answer pairs generated with\n"
        "[dataset-generator](https://github.com/KevinDeBenedetti/dataset-generator).\n"
    )
    assert is_app_card(legacy) is True


def test_any_card_of_a_job_dataset_is_the_apps():
    hub = InMemoryHub()
    hub.push(
        REPO,
        {
            ROOT_PAIRS_PATH: to_jsonl([row(1)]),
            MANIFEST_PATH: b"{}",
            CARD_PATH: b"---\npretty_name: GitHub Q&A\n---\n",
        },
    )
    assert opened(hub).read().app_card is True


@pytest.mark.parametrize("card", [None, "", "  \n"])
def test_a_missing_or_blank_card_has_nothing_to_protect(card):
    assert is_app_card(card) is True


@pytest.mark.parametrize(
    "card, expected",
    [
        ("# Title\n", "---\ntags:\n- dataset-generator\n---\n\n# Title\n"),
        (
            "---\nlanguage:\n- en\n---\n\n# T\n",
            "---\nlanguage:\n- en\ntags:\n- dataset-generator\n---\n\n# T\n",
        ),
        (
            "---\ntags:\n- github\n- synthetic\nlicense: mit\n---\nbody\n",
            "---\ntags:\n- dataset-generator\n- github\n- synthetic\nlicense: mit\n---\nbody\n",
        ),
        (
            "---\ntags:\n  - github\n---\n",
            "---\ntags:\n  - dataset-generator\n  - github\n---\n",
        ),
        (
            "---\ntags: [github, 'qa']\nlicense: mit\n---\n",
            "---\ntags:\n- github\n- qa\n- dataset-generator\nlicense: mit\n---\n",
        ),
        ("---\n---\n\nbody\n", "---\ntags:\n- dataset-generator\n---\n\nbody\n"),
    ],
)
def test_marking_a_card_adds_the_tag_and_changes_nothing_else(card, expected):
    marked = mark_app_card(card)
    assert marked == expected
    assert is_app_card(marked) is True
    assert mark_app_card(marked) == marked


def test_a_tag_in_the_body_does_not_make_a_card_the_apps():
    assert (
        is_app_card("---\nlicense: mit\n---\n\ntags:\n- dataset-generator\n") is False
    )


# --- the real Hub's answers --------------------------------------------------


def _http_error(status: int) -> HfHubHTTPError:
    response = httpx.Response(
        status, request=httpx.Request("POST", "https://huggingface.co/api")
    )
    return HfHubHTTPError(f"HTTP {status}", response=response)


class StubHfApi:
    """An ``HfApi`` answering from attributes; records the commit it is asked for."""

    def __init__(self):
        self.commit_error = None
        self.commit_kwargs = None
        self.created = None

    def whoami(self):
        raise _http_error(401)

    def repo_info(self, repo_id, **kwargs):
        raise RepositoryNotFoundError("no repo", response=_http_error(404).response)

    def create_repo(self, repo_id, **kwargs):
        self.created = {"repo_id": repo_id, **kwargs}

    def create_commit(self, **kwargs):
        self.commit_kwargs = kwargs
        if self.commit_error is not None:
            raise self.commit_error
        return SimpleNamespace(oid="c" * 40)


@pytest.fixture
def stub():
    hub_repo.forget_downloads()
    return StubHfApi()


def backend(stub: StubHfApi) -> HfHubBackend:
    return HfHubBackend("hf_test_token", "fingerprint", client=stub)


def test_the_hub_refusing_the_token_is_a_rejected_token(stub):
    with pytest.raises(HubTokenRejected, match="rejected your token"):
        backend(stub).account()


def test_an_unknown_repo_has_no_head(stub):
    assert backend(stub).head(REPO, [ROOT_PAIRS_PATH]) is None


def test_a_repo_is_only_ever_created_private(stub):
    backend(stub).create_private(REPO)
    assert stub.created == {
        "repo_id": REPO,
        "repo_type": "dataset",
        "private": True,
        "exist_ok": True,
    }


def test_a_commit_names_its_parent(stub):
    oid = backend(stub).commit(REPO, {ROOT_PAIRS_PATH: b"{}\n"}, "p" * 40, "msg")
    assert oid == "c" * 40
    assert stub.commit_kwargs["parent_commit"] == "p" * 40
    assert stub.commit_kwargs["commit_message"] == "msg"
    assert [op.path_in_repo for op in stub.commit_kwargs["operations"]] == [
        ROOT_PAIRS_PATH
    ]


@pytest.mark.parametrize("status", [409, 412])
def test_a_commit_the_hub_refuses_as_stale_is_a_moved_dataset(stub, status):
    stub.commit_error = _http_error(status)
    with pytest.raises(DatasetMoved):
        backend(stub).commit(REPO, {ROOT_PAIRS_PATH: b""}, "p" * 40, "msg")


def test_any_other_commit_failure_is_not_disguised(stub):
    stub.commit_error = _http_error(500)
    with pytest.raises(HfHubHTTPError):
        backend(stub).commit(REPO, {ROOT_PAIRS_PATH: b""}, "p" * 40, "msg")


def test_a_file_is_downloaded_once_per_commit_and_capped(stub, monkeypatch, tmp_path):
    calls = []

    def fake_download(**kwargs):
        calls.append((kwargs["filename"], kwargs["revision"]))
        path = tmp_path / "file"
        path.write_bytes(b"0123456789")
        return str(path)

    monkeypatch.setattr("huggingface_hub.hf_hub_download", fake_download)
    hub = backend(stub)
    assert hub.download(REPO, ROOT_PAIRS_PATH, "a" * 40, 10) == b"0123456789"
    assert hub.download(REPO, ROOT_PAIRS_PATH, "a" * 40, 10) == b"0123456789"
    assert calls == [(ROOT_PAIRS_PATH, "a" * 40)]
    with pytest.raises(DatasetTooLarge):
        hub.download(REPO, ROOT_PAIRS_PATH, "a" * 40, 9)
    with pytest.raises(DatasetTooLarge):
        hub.download(REPO, ROOT_PAIRS_PATH, "b" * 40, 9)


def test_a_hub_that_answers_a_server_error_is_unavailable_not_a_bad_token():
    from server.services.hub_repo import HfHubBackend, HubTokenRejected, HubUnavailable

    class DownHfApi(StubHfApi):
        def __init__(self, status):
            super().__init__()
            self.status = status

        def whoami(self):
            raise _http_error(self.status)

        def repo_info(self, repo_id, **kwargs):
            raise _http_error(self.status)

    down = HfHubBackend("hf_x", "k", client=DownHfApi(503))
    with pytest.raises(HubUnavailable):
        down.account()
    with pytest.raises(HubUnavailable):
        down.head("kevin/x", ["train.jsonl"])

    refused = HfHubBackend("hf_x", "k", client=DownHfApi(401))
    with pytest.raises(HubTokenRejected):
        refused.account()
    # A token the Hub refuses for this repo is not an outage either.
    with pytest.raises(HubTokenRejected):
        HfHubBackend("hf_x", "k", client=DownHfApi(403)).head("kevin/x", ["a"])
