"""An in-memory Hugging Face Hub for tests: the second adapter of
``services.hub_repo.HubBackend``.

It keeps every commit of every repo, so a test can publish, read back, and
make the repo move between a read and a publication (:meth:`InMemoryHub.push`)
without patching anything.
"""

import hashlib
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from server.services.hub_repo import (
    DatasetMoved,
    DatasetTooLarge,
    DatasetUnreadable,
    HubTokenRejected,
    HubUnavailable,
    RepoHead,
)


@dataclass
class _Commit:
    oid: str
    files: Dict[str, bytes]
    message: str
    parent: Optional[str]


@dataclass
class _Repo:
    private: Optional[bool]
    commits: List[_Commit] = field(default_factory=list)


class InMemoryHub:
    """Dataset repos held in memory. ``account=None`` is a token naming nobody;
    ``rejects_token=True`` is a token the Hub refuses; ``unavailable=True`` is
    a Hub that is down (every call fails with a server or network error)."""

    def __init__(
        self, account: Optional[str] = "kevin", *, rejects_token: bool = False
    ) -> None:
        self._account = account
        self.rejects_token = rejects_token
        self.unavailable = False
        # Called once each, oldest first, right before a commit is checked: a
        # test makes the repo move between a read and the publication with it.
        self.before_commit: List[Callable[[], None]] = []
        self._repos: Dict[str, _Repo] = {}
        self.downloads: List[str] = []

    # --- what a test sets up and looks at -----------------------------------

    def push(
        self,
        repo_id: str,
        files: Mapping[str, bytes],
        *,
        private: Optional[bool] = True,
        message: str = "pushed from elsewhere",
    ) -> str:
        """Commit ``files`` on top of whatever is there, creating the repo if
        needed: someone else's push, or a test's starting point."""
        repo = self._repos.setdefault(repo_id, _Repo(private))
        return self._append(repo, repo_id, files, message)

    def set_private(self, repo_id: str, private: Optional[bool]) -> None:
        self._repos[repo_id].private = private

    def is_private(self, repo_id: str) -> Optional[bool]:
        return self._repos[repo_id].private

    def delete(self, repo_id: str) -> None:
        del self._repos[repo_id]

    def exists(self, repo_id: str) -> bool:
        return repo_id in self._repos

    def files(self, repo_id: str) -> Dict[str, bytes]:
        """The repo's files at its latest commit."""
        return dict(self._repos[repo_id].commits[-1].files)

    def log(self, repo_id: str) -> List[str]:
        """Commit messages, oldest first."""
        return [c.message for c in self._repos[repo_id].commits]

    # --- HubBackend ----------------------------------------------------------

    def _down(self) -> None:
        if self.unavailable:
            raise HubUnavailable(
                "The Hugging Face Hub didn't answer. Try again shortly."
            )

    def account(self) -> Optional[str]:
        self._down()
        if self.rejects_token:
            raise HubTokenRejected("Hugging Face rejected your token.")
        return self._account

    def head(self, repo_id: str, paths: Sequence[str]) -> Optional[RepoHead]:
        self._down()
        repo = self._repos.get(repo_id)
        if repo is None:
            return None
        last = repo.commits[-1]
        sizes = {p: len(last.files[p]) for p in paths if p in last.files}
        return RepoHead(last.oid, repo.private, sizes)

    def download(self, repo_id: str, path: str, commit: str, max_bytes: int) -> bytes:
        self._down()
        self.downloads.append(path)
        for known in self._repos[repo_id].commits:
            if known.oid == commit:
                if path not in known.files:
                    raise DatasetUnreadable(f"'{path}' is no longer in '{repo_id}'")
                data = known.files[path]
                if len(data) > max_bytes:
                    raise DatasetTooLarge(f"'{repo_id}' is too large to read")
                return data
        raise DatasetUnreadable(f"'{repo_id}' has no commit {commit}")

    def create_private(self, repo_id: str) -> None:
        if repo_id in self._repos:
            return  # like the Hub: `private` is ignored for an existing repo
        repo = self._repos[repo_id] = _Repo(private=True)
        self._append(repo, repo_id, {".gitattributes": b""}, "initial commit")

    def commit(
        self,
        repo_id: str,
        files: Mapping[str, Any],
        parent: str,
        message: str,
        delete: Sequence[str] = (),
    ) -> str:
        from pathlib import Path

        if self.before_commit:
            self.before_commit.pop(0)()
        repo = self._repos[repo_id]
        if repo.commits[-1].oid != parent:
            raise DatasetMoved(f"The dataset '{repo_id}' changed since it was read.")
        contents = {
            path: value.read_bytes() if isinstance(value, Path) else value
            for path, value in files.items()
        }
        return self._append(repo, repo_id, contents, message, delete)

    def list_files(self, repo_id: str, commit: str) -> List[str]:
        for known in self._repos[repo_id].commits:
            if known.oid == commit:
                return sorted(known.files)
        raise DatasetUnreadable(f"'{repo_id}' has no commit {commit}")

    def _append(
        self,
        repo: _Repo,
        repo_id: str,
        files: Mapping[str, bytes],
        message: str,
        delete: Sequence[str] = (),
    ) -> str:
        previous = repo.commits[-1] if repo.commits else None
        merged = {**(previous.files if previous else {}), **files}
        for path in delete:
            merged.pop(path, None)
        seed = f"{repo_id}:{len(repo.commits)}:{message}".encode()
        oid = hashlib.sha1(seed, usedforsecurity=False).hexdigest()
        repo.commits.append(
            _Commit(oid, merged, message, previous.oid if previous else None)
        )
        return oid
