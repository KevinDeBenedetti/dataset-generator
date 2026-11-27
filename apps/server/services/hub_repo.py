"""A Hub dataset repo: open it, read a dataset version, publish the next one.

One Q&A dataset lives in one private dataset repo on the Hugging Face Hub.
This module is the only place that knows how such a repo is laid out and how a
publication stays safe:

* **Open** checks the caller's token and completes a bare repo name. Nothing is
  created: a draft that is never published leaves no empty repo behind.
* **Read** returns a :class:`DatasetVersion` — the rows, the review list, the
  manifest and the card, all at one commit — under the import size cap.
* **Publish** writes the next version in one commit, on top of the commit that
  was read. The Hub refuses the commit when the repo changed in between
  (:class:`DatasetMoved`): nothing is ever overwritten silently, and what to do
  next is the caller's decision. The repo is created private, or must already
  be (:class:`RepoNotPrivate`).

Layout. The rows live in ``train.jsonl`` at the root (the Q&A jobs, with
``review.jsonl`` and ``manifest.json`` next to it) or in ``data/train.jsonl``
(file and web page drafts). A read finds the file the repo already has and a
publication writes back to that same file, so no caller needs to know which.

Cards. A publication replaces the card only when the app wrote it
(:func:`is_app_card`); a card written elsewhere is the owner's and stays.

The Hub itself sits behind :class:`HubBackend`: :class:`HfHubBackend` talks to
the real one, the tests' in-memory repo (tests/fake_hub.py) keeps commits.

Browsing datasets (tables, statistics, compare) is services/hub.py.
"""

import json
import logging
import re
import tempfile
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Sequence

from server.core.config import config
from server.core.lru import WeightedLRU
from server.services.credentials import HF_TOKEN, Credentials

logger = logging.getLogger(__name__)

ROOT_PAIRS_PATH = "train.jsonl"
DATA_PAIRS_PATH = "data/train.jsonl"
REVIEW_PATH = "review.jsonl"
MANIFEST_PATH = "manifest.json"
CARD_PATH = "README.md"
_KNOWN_PATHS = (ROOT_PAIRS_PATH, DATA_PAIRS_PATH, REVIEW_PATH, MANIFEST_PATH, CARD_PATH)

# The front-matter tag every card the app writes carries.
APP_CARD_TAG = "dataset-generator"
# Cards from before the tag: the file and web page drafts' card links here.
_LEGACY_CARD_LINK = (
    "[dataset-generator](https://github.com/KevinDeBenedetti/dataset-generator)"
)


# --- errors ------------------------------------------------------------------


class HubRepoError(Exception):
    """Base of everything this module raises; the message is fit for the user."""


class HubTokenMissing(HubRepoError):
    """The caller has no Hugging Face token."""


class HubTokenRejected(HubRepoError):
    """The Hub refused the token, or it names no account to publish under."""


class RepoNotPrivate(HubRepoError):
    """The repo exists and is not confirmed private: publishing would leak."""


class RepoNotOurs(HubRepoError):
    """The repo holds a dataset the app didn't make: it is not overwritten."""


class DatasetMoved(HubRepoError):
    """The repo changed since the version being published on top of was read."""


class HubUnavailable(HubRepoError):
    """The Hub answered with a server error, or could not be reached."""


class DatasetUnreadable(HubRepoError):
    """A file of the dataset could not be read as what it should be."""


class DatasetTooLarge(DatasetUnreadable):
    """The dataset's files exceed ``config.max_hub_import_bytes``."""


_UNAVAILABLE = "The Hugging Face Hub didn't answer. Try again shortly."


def _refused(exc: Exception) -> bool:
    """Whether an HTTP error from the Hub is a refusal of the token itself."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return status in (401, 403)


_REFUSAL_MESSAGE = (
    "Hugging Face rejected your token. Check it in Settings (it needs write access)."
)


def _hub_error(exc: Exception) -> HubRepoError:
    """What a failed Hub call means for the user: a refused token, or a Hub
    that is down (a server error, or no answer at all)."""
    if _refused(exc):
        return HubTokenRejected(_REFUSAL_MESSAGE)
    return HubUnavailable(_UNAVAILABLE)


# --- the seam ----------------------------------------------------------------


@dataclass(frozen=True)
class RepoHead:
    """A repo at its latest commit: visibility and the sizes of the files asked for."""

    commit: str
    private: Optional[bool]
    sizes: Dict[str, int]


class HubBackend(Protocol):
    """What this module needs from the Hub, and nothing more."""

    def account(self) -> Optional[str]:
        """The token's account name. Raises :class:`HubTokenRejected`."""
        ...

    def head(self, repo_id: str, paths: Sequence[str]) -> Optional[RepoHead]:
        """The repo's latest commit, or None when the repo does not exist."""
        ...

    def download(self, repo_id: str, path: str, commit: str, max_bytes: int) -> bytes:
        """A file's bytes at ``commit``. Raises :class:`DatasetTooLarge` past ``max_bytes``."""
        ...

    def create_private(self, repo_id: str) -> None:
        """Create the repo private; an existing repo is left as it is."""
        ...

    def commit(
        self,
        repo_id: str,
        files: Mapping[str, Any],
        parent: str,
        message: str,
        delete: Sequence[str] = (),
    ) -> str:
        """Write ``files`` (bytes, or a local ``Path`` streamed from disk) and
        remove ``delete`` in one commit on ``parent``; the new commit's id.

        Raises :class:`DatasetMoved` when the repo's head is no longer ``parent``.
        """
        ...

    def list_files(self, repo_id: str, commit: str) -> List[str]:
        """Every file path of the repo at ``commit``."""
        ...

    def set_private(self, repo_id: str, private: bool) -> None:
        """Make the repo private or public."""
        ...


# --- the real Hub ------------------------------------------------------------

# (token fingerprint, repo, commit, path) -> that file's bytes. A commit's
# content never changes, so an entry is never stale, and the token in the key
# keeps one account's download from ever serving another.
_downloads = WeightedLRU(lambda: config.max_hub_import_bytes, len)


def forget_downloads() -> None:
    """Drop every cached file (tests)."""
    _downloads.clear()


def _too_large(repo_id: str) -> DatasetTooLarge:
    return DatasetTooLarge(
        f"'{repo_id}' is too large to read: its files exceed "
        f"{config.max_hub_import_bytes // (1024 * 1024)} MB"
    )


class HfHubBackend:
    """The Hugging Face Hub, through ``huggingface_hub`` (imported lazily)."""

    def __init__(self, token: str, cache_key: str, client: Any = None) -> None:
        self._token = token
        self._cache_key = cache_key
        # An ``HfApi``; built on first use so the SDK stays optional at boot.
        self._client: Any = client

    @property
    def _api(self) -> Any:
        if self._client is None:
            from huggingface_hub import HfApi

            self._client = HfApi(token=self._token)
        return self._client

    def account(self) -> Optional[str]:
        from huggingface_hub.errors import HfHubHTTPError

        try:
            name = self._api.whoami().get("name")
        except (HfHubHTTPError, OSError) as exc:  # OSError: DNS, refused, timeout
            raise _hub_error(exc) from exc
        return str(name) if name else None

    def head(self, repo_id: str, paths: Sequence[str]) -> Optional[RepoHead]:
        from huggingface_hub.errors import HfHubHTTPError, RepositoryNotFoundError
        from huggingface_hub.hf_api import RepoFile

        try:
            info = self._api.repo_info(repo_id, repo_type="dataset")
            found = self._api.get_paths_info(
                repo_id, list(paths), repo_type="dataset", revision=info.sha
            )
        except RepositoryNotFoundError:
            return None
        except (HfHubHTTPError, OSError) as exc:
            raise _hub_error(exc) from exc
        sizes = {f.path: f.size for f in found if isinstance(f, RepoFile)}
        return RepoHead(str(info.sha), getattr(info, "private", None), sizes)

    def download(self, repo_id: str, path: str, commit: str, max_bytes: int) -> bytes:
        from huggingface_hub import hf_hub_download
        from huggingface_hub.errors import (
            EntryNotFoundError,
            HfHubHTTPError,
            RevisionNotFoundError,
        )

        key = (self._cache_key, repo_id, commit, path)
        cached = _downloads.get(key)
        if cached is not None:
            if len(cached) > max_bytes:
                raise _too_large(repo_id)
            return cached
        # A throwaway cache directory: reads never pile up on the server's disk.
        with tempfile.TemporaryDirectory(prefix="hf-repo-") as cache_dir:
            try:
                local = hf_hub_download(
                    repo_id=repo_id,
                    filename=path,
                    repo_type="dataset",
                    revision=commit,
                    token=self._token,
                    cache_dir=cache_dir,
                )
            except EntryNotFoundError as exc:
                raise DatasetUnreadable(
                    f"'{path}' is no longer in '{repo_id}'"
                ) from exc
            except RevisionNotFoundError as exc:  # rewritten or deleted on the Hub
                raise DatasetUnreadable(
                    f"'{repo_id}' no longer has the version being read"
                ) from exc
            except (HfHubHTTPError, OSError) as exc:
                raise _hub_error(exc) from exc
            with open(local, "rb") as f:
                data = f.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise _too_large(repo_id)
        _downloads.put(key, data)
        return data

    def create_private(self, repo_id: str) -> None:
        self._api.create_repo(repo_id, repo_type="dataset", private=True, exist_ok=True)

    def commit(
        self,
        repo_id: str,
        files: Mapping[str, Any],
        parent: str,
        message: str,
        delete: Sequence[str] = (),
    ) -> str:
        from pathlib import Path

        from huggingface_hub import CommitOperationAdd, CommitOperationDelete
        from huggingface_hub.errors import HfHubHTTPError

        # A Path is streamed by huggingface_hub (LFS/Xet), never read whole.
        operations: List[Any] = [
            CommitOperationAdd(
                path, str(content) if isinstance(content, Path) else content
            )
            for path, content in files.items()
        ]
        operations += [CommitOperationDelete(path) for path in delete]
        try:
            info = self._api.create_commit(
                repo_id=repo_id,
                repo_type="dataset",
                operations=operations,
                commit_message=message,
                parent_commit=parent,
            )
        except HfHubHTTPError as exc:
            # 412 Precondition Failed: the branch no longer points at `parent`.
            # 409 is what a commit racing another one answers.
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (409, 412):
                raise _moved(repo_id) from exc
            raise
        return str(info.oid)

    def list_files(self, repo_id: str, commit: str) -> List[str]:
        from huggingface_hub.errors import HfHubHTTPError

        try:
            return list(
                self._api.list_repo_files(repo_id, repo_type="dataset", revision=commit)
            )
        except (HfHubHTTPError, OSError) as exc:
            raise _hub_error(exc) from exc

    def set_private(self, repo_id: str, private: bool) -> None:
        from huggingface_hub.errors import HfHubHTTPError

        try:
            self._api.update_repo_settings(
                repo_id, repo_type="dataset", private=private
            )
        except (HfHubHTTPError, OSError) as exc:
            raise _hub_error(exc) from exc


# --- a dataset version -------------------------------------------------------


@dataclass(frozen=True)
class DatasetVersion:
    """The content of a Hub dataset repo at one commit.

    ``commit`` is None for a repo that does not exist yet (every list empty).
    ``rows`` are the pairs file's rows exactly as stored — a Q&A job's own rows
    and any foreign row alike. ``pairs_path`` is where they live, which a card
    written for this dataset must point its viewer at.
    """

    repo_id: str
    commit: Optional[str]
    pairs_path: str
    rows: List[Dict[str, Any]] = field(default_factory=list)
    review: List[Dict[str, Any]] = field(default_factory=list)
    manifest: Optional[Dict[str, Any]] = None
    card: Optional[str] = None
    app_card: bool = True

    @property
    def url(self) -> str:
        return f"https://huggingface.co/datasets/{self.repo_id}"


def _moved(repo_id: str) -> DatasetMoved:
    return DatasetMoved(
        f"The dataset '{repo_id}' changed on Hugging Face since it was read."
    )


def _jsonl_rows(repo_id: str, path: str, raw: bytes) -> List[Dict[str, Any]]:
    """Every row of a JSON Lines file. A line that is not a JSON object stops
    the read: skipping it would drop it from the next publication."""
    rows: List[Dict[str, Any]] = []
    try:
        text = raw.decode("utf-8-sig")
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"line {number} is not a JSON object")
            rows.append(row)
    except ValueError as exc:  # JSONDecodeError and UnicodeDecodeError included
        raise DatasetUnreadable(
            f"'{path}' in '{repo_id}' is not valid JSON Lines: {exc}"
        ) from exc
    return rows


def to_jsonl(rows: Sequence[Mapping[str, Any]]) -> bytes:
    """One compact JSON object per line, in the order given."""
    if not rows:
        return b""
    lines = [
        json.dumps(dict(row), ensure_ascii=False, separators=(",", ":")) for row in rows
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


# --- cards -------------------------------------------------------------------

_FRONT_MATTER = re.compile(r"\A---[ \t]*\n(.*?\n)?---[ \t]*(?:\n|\Z)", re.DOTALL)
_TAGS_LINE = re.compile(r"^tags:[ \t]*(.*)$", re.MULTILINE)
_ITEM = re.compile(r"^([ \t]*)-[ \t]*(.+?)[ \t]*$")


def _front_matter(card: str) -> Optional[str]:
    match = _FRONT_MATTER.match(card)
    return (match.group(1) or "") if match else None


def _card_tags(card: str) -> List[str]:
    """The ``tags`` of a card's front matter (block or inline list)."""
    front = _front_matter(card)
    if front is None:
        return []
    line = _TAGS_LINE.search(front)
    if line is None:
        return []
    inline = line.group(1).strip()
    if inline:
        return [
            t.strip().strip("'\"") for t in inline.strip("[]").split(",") if t.strip()
        ]
    tags: List[str] = []
    for following in front[line.end() :].splitlines():
        if not following.strip():
            continue
        item = _ITEM.match(following)
        if item is None:
            break
        tags.append(item.group(2).strip("'\""))
    return tags


def is_app_card(card: Optional[str], *, has_manifest: bool = False) -> bool:
    """Whether the app wrote this card, and may therefore replace it.

    True for the app's tag, for the file and web page drafts' card from before
    the tag, and for any card of a repo with a ``manifest.json`` (only the Q&A
    jobs write one). A repo without a card has nothing to protect.
    """
    if card is None or not card.strip() or has_manifest:
        return True
    return APP_CARD_TAG in _card_tags(card) or _LEGACY_CARD_LINK in card


def mark_app_card(card: str) -> str:
    """``card`` with the app's tag in its front matter, added when missing."""
    tags = _card_tags(card)
    if APP_CARD_TAG in tags:
        return card
    front = _front_matter(card)
    if front is None:
        return f"---\ntags:\n- {APP_CARD_TAG}\n---\n\n{card}"
    start = card.index("\n") + 1  # after the opening `---` line
    line = _TAGS_LINE.search(front)
    if line is None:
        end = start + len(front)
        return f"{card[:end]}tags:\n- {APP_CARD_TAG}\n{card[end:]}"
    if line.group(1).strip():
        # An inline list: rewritten as a block with the tag appended.
        block = "tags:\n" + "".join(f"- {t}\n" for t in [*tags, APP_CARD_TAG])
        return f"{card[: start + line.start()]}{block.rstrip()}{card[start + line.end() :]}"
    # A block list: the tag goes first, indented like the item that follows.
    rest = front[line.end() :].lstrip("\n")
    first = _ITEM.match(rest.splitlines()[0]) if rest else None
    indent = first.group(1) if first else ""
    at = start + line.end()
    return f"{card[:at]}\n{indent}- {APP_CARD_TAG}{card[at:]}"


# --- the module --------------------------------------------------------------


class HubDatasetRepo:
    """One Hub dataset repo, opened for one user. Made by :func:`open_repo`."""

    def __init__(
        self,
        backend: HubBackend,
        repo_id: str,
        new_pairs_path: str,
        before_publish: Optional[Callable[[], None]] = None,
    ) -> None:
        self._backend = backend
        self.repo_id = repo_id
        self._new_pairs_path = new_pairs_path
        # Run before anything is written (open_repo: the token's re-check).
        self._before_publish = before_publish

    def read(self) -> DatasetVersion:
        """The dataset as it is now. A repo that does not exist is an empty version.

        Raises :class:`DatasetTooLarge` before anything is downloaded when the
        files' announced sizes exceed the cap, and :class:`DatasetUnreadable`
        for a rows file, review list or manifest that is not what it should be.
        """
        head = self._backend.head(self.repo_id, _KNOWN_PATHS)
        if head is None:
            return DatasetVersion(self.repo_id, None, self._new_pairs_path)
        present = [p for p in _KNOWN_PATHS if p in head.sizes]
        pairs_path = next(
            (p for p in (ROOT_PAIRS_PATH, DATA_PAIRS_PATH) if p in head.sizes),
            self._new_pairs_path,
        )
        wanted = [
            p
            for p in present
            if p in (pairs_path, REVIEW_PATH, MANIFEST_PATH, CARD_PATH)
        ]
        budget = config.max_hub_import_bytes
        if sum(head.sizes[p] or 0 for p in wanted) > budget:
            raise _too_large(self.repo_id)

        contents: Dict[str, bytes] = {}
        for path in wanted:
            raw = self._backend.download(self.repo_id, path, head.commit, budget)
            budget -= len(raw)
            contents[path] = raw

        manifest: Optional[Dict[str, Any]] = None
        if MANIFEST_PATH in contents:
            try:
                manifest = json.loads(contents[MANIFEST_PATH].decode("utf-8-sig"))
            except ValueError as exc:
                raise DatasetUnreadable(
                    f"'{MANIFEST_PATH}' in '{self.repo_id}' is not valid JSON: {exc}"
                ) from exc
            if not isinstance(manifest, dict):
                raise DatasetUnreadable(
                    f"'{MANIFEST_PATH}' in '{self.repo_id}' is not a JSON object"
                )
        card = (
            contents[CARD_PATH].decode("utf-8", errors="replace")
            if CARD_PATH in contents
            else None
        )
        return DatasetVersion(
            repo_id=self.repo_id,
            commit=head.commit,
            pairs_path=pairs_path,
            rows=_jsonl_rows(self.repo_id, pairs_path, contents.get(pairs_path, b"")),
            review=_jsonl_rows(
                self.repo_id, REVIEW_PATH, contents.get(REVIEW_PATH, b"")
            ),
            manifest=manifest,
            card=card,
            app_card=is_app_card(card, has_manifest=manifest is not None),
        )

    def publish(
        self,
        base: DatasetVersion,
        rows: Sequence[Mapping[str, Any]],
        *,
        card: Optional[str],
        message: str,
        review: Optional[Sequence[Mapping[str, Any]]] = None,
        manifest: Optional[Mapping[str, Any]] = None,
    ) -> DatasetVersion:
        """Publish the version after ``base``, in one commit; that new version.

        ``rows`` is the whole pairs file, written where ``base`` found it.
        ``card`` replaces the dataset's card only when the app wrote the one
        there (``base.app_card``); None leaves the card alone either way. ``manifest`` and ``review`` are a Q&A job's:
        given a manifest, both files are written with the rows — the manifest
        must never land without the pairs it describes — and left alone
        otherwise.

        Raises :class:`DatasetMoved` when the repo is no longer at ``base``
        (nothing is written) and :class:`RepoNotPrivate` for a repo that is not
        confirmed private.
        """
        if base.repo_id != self.repo_id:
            raise ValueError(
                f"a version of '{base.repo_id}' cannot be published to '{self.repo_id}'"
            )
        if self._before_publish is not None:
            self._before_publish()
        if base.commit is None:
            self._backend.create_private(self.repo_id)
        head = self._backend.head(self.repo_id, _KNOWN_PATHS)
        if head is None:
            raise _moved(self.repo_id)  # deleted since the read
        # Only a confirmed private repo is safe: an unknown visibility is
        # refused like a public one (`private=True` is ignored by the Hub when
        # the repo already exists).
        if head.private is not True:
            state = (
                "is public" if head.private is False else "has an unknown visibility"
            )
            raise RepoNotPrivate(
                f"The Hugging Face repo '{self.repo_id}' {state}. Publishing would "
                "expose this dataset: make the repo private on the Hub, or "
                "publish to a different repo."
            )
        if base.commit is None:
            # Read as missing: someone else filling it since is a moved dataset.
            if any(p in head.sizes for p in (ROOT_PAIRS_PATH, DATA_PAIRS_PATH)):
                raise _moved(self.repo_id)
            parent = head.commit
        else:
            parent = base.commit

        files: Dict[str, bytes] = {base.pairs_path: to_jsonl(rows)}
        new_manifest = base.manifest
        new_review = list(base.review)
        if manifest is not None:
            new_manifest = dict(manifest)
            # Rewritten every time (empty included) so a stale list never lingers.
            new_review = [dict(r) for r in (review or [])]
            files[REVIEW_PATH] = to_jsonl(new_review)
            files[MANIFEST_PATH] = (
                json.dumps(new_manifest, indent=2, ensure_ascii=False) + "\n"
            ).encode("utf-8")
        new_card = base.card
        if card is not None and base.app_card:
            new_card = mark_app_card(card)
            files[CARD_PATH] = new_card.encode("utf-8")

        commit = self._backend.commit(self.repo_id, files, parent, message)
        logger.info("published %d row(s) to %s at %s", len(rows), self.repo_id, commit)
        return DatasetVersion(
            repo_id=self.repo_id,
            commit=commit,
            pairs_path=base.pairs_path,
            rows=[dict(r) for r in rows],
            review=new_review,
            manifest=new_manifest,
            card=new_card,
            app_card=base.app_card,
        )

    # --- tabular datasets (ADR 0005) ------------------------------------------

    def publish_table(
        self,
        shards: Mapping[str, Any],
        *,
        card: str,
        manifest: bytes,
        message: str,
        public: bool = False,
    ) -> Dict[str, Any]:
        """Publish a tabular dataset's next version in one commit: its Parquet
        shards (``data/…parquet`` → local ``Path``), the app card and the
        manifest; the shards of the previous version that are not rewritten
        are removed in the same commit.

        A new repo is created private, and made public only once the commit
        is in, when ``public`` is asked. An existing repo must be the app's (an
        app card, or empty) and, for a private publication, confirmed private.
        Raises :class:`DatasetMoved` when the repo changes in between.
        """
        if self._before_publish is not None:
            self._before_publish()
        head = self._backend.head(self.repo_id, [CARD_PATH, MANIFEST_PATH])
        if head is None:
            self._backend.create_private(self.repo_id)
            head = self._backend.head(self.repo_id, [CARD_PATH, MANIFEST_PATH])
            if head is None:  # pragma: no cover — created a moment ago
                raise _moved(self.repo_id)
        elif CARD_PATH in head.sizes:
            existing = self._backend.download(
                self.repo_id, CARD_PATH, head.commit, 1024 * 1024
            ).decode("utf-8", errors="replace")
            if not is_app_card(existing, has_manifest=MANIFEST_PATH in head.sizes):
                raise RepoNotOurs(
                    f"The Hugging Face repo '{self.repo_id}' has a card the app "
                    "didn't write: publish to another repo"
                )
        if not public and head.private is not True:
            state = (
                "is public" if head.private is False else "has an unknown visibility"
            )
            raise RepoNotPrivate(
                f"The Hugging Face repo '{self.repo_id}' {state}. Publishing would "
                "expose this dataset: make the repo private on the Hub, or "
                "publish to a different repo."
            )
        old = [
            path
            for path in self._backend.list_files(self.repo_id, head.commit)
            if path.startswith("data/") and path not in shards
        ]
        files: Dict[str, Any] = {
            **shards,
            CARD_PATH: card.encode("utf-8"),
            MANIFEST_PATH: manifest,
        }
        commit = self._backend.commit(
            self.repo_id, files, head.commit, message, delete=old
        )
        if public and head.private is not False:
            self._backend.set_private(self.repo_id, False)
        return {
            "repo_id": self.repo_id,
            "commit": commit,
            "url": f"https://huggingface.co/datasets/{self.repo_id}",
            "visibility": "public" if public else "private",
        }


def backend_for(creds: Credentials) -> HubBackend:
    """The real Hub, as the caller's token sees it.

    The one place the app picks its adapter: a test that wants the in-memory
    Hub everywhere replaces this function (the ``memory_hub`` fixture).
    """
    from server.services.huggingface import token_fingerprint

    return HfHubBackend(creds.secret(HF_TOKEN), token_fingerprint(creds))


def open_repo(
    creds: Credentials,
    repo_id: str,
    *,
    new_pairs_path: str = DATA_PAIRS_PATH,
    backend: Optional[HubBackend] = None,
) -> HubDatasetRepo:
    """Open a Hub dataset repo for the caller: token checked, repo id completed.

    Nothing is created and nothing is read. A bare name (``github-qa``) is
    completed with the namespace saved in Settings, or the token's own account
    — every Hub endpoint but repo creation answers 404 to a bare one.
    ``new_pairs_path`` is where the rows of a repo that has none yet will go.
    ``backend`` replaces :func:`backend_for`'s.

    Raises :class:`HubTokenMissing` without a token and
    :class:`HubTokenRejected` when the Hub refuses it or no namespace can be
    worked out.
    """
    if not creds.has(HF_TOKEN):
        raise HubTokenMissing(
            "Hugging Face is not configured. Add your Hugging Face token "
            "(with write access) in Settings to use the Hub."
        )
    before_publish = None
    if backend is None:
        backend = backend_for(creds)
        before_publish = _token_check(creds)
    account = backend.account()
    repo_id = repo_id.strip()
    if "/" not in repo_id:
        namespace = creds.hf_namespace or account
        if not namespace:
            raise HubTokenRejected(
                f"Hugging Face repo '{repo_id}' has no namespace and none could "
                "be determined. Use the full 'user/name' id, or set your "
                "namespace in Settings."
            )
        repo_id = f"{namespace}/{repo_id}"
    return HubDatasetRepo(backend, repo_id, new_pairs_path, before_publish)


def _token_check(creds: Credentials) -> Callable[[], None]:
    """The re-check of the token before a publication (auth/hf_token.py): a
    revoked or read-only token is refused before anything is written."""

    def check() -> None:
        from server.auth.hf_token import TokenUnusable, ensure_can_publish

        try:
            ensure_can_publish(creds)
        except TokenUnusable as exc:
            raise HubTokenRejected(str(exc)) from None

    return check
