"""The contract every connector meets (ADR 0001).

A connector turns a data source's ``config`` into local files plus their
:class:`Provenance`: where and when the rows came from. The engine
(apps/server/engine) reads the files; the fingerprint tells a scheduled refresh
whether anything changed.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Protocol, Type

from pydantic import BaseModel

from server.services.credentials import Credentials

FileFormat = Literal["csv", "tsv", "json", "jsonl", "parquet", "xlsx"]
FORMATS: tuple = ("csv", "tsv", "json", "jsonl", "parquet", "xlsx")


class ConnectorError(ValueError):
    """A data source that can't be fetched as configured: the message is for the user."""


class ConnectorSpec(BaseModel):
    """What the web shows to configure a data source of this kind."""

    kind: str
    title: str
    description: str
    config_schema: Dict[str, Any]
    secret_kind: Optional[str] = None
    # Created by its own route (an upload), not by POST /data-sources.
    created_by_upload: bool = False


@dataclass
class Provenance:
    connector: str
    fetched_at: datetime
    sha256: str
    bytes: int
    url: Optional[str] = None
    resource_id: Optional[str] = None
    licence: Optional[str] = None
    licence_url: Optional[str] = None
    producer: Optional[str] = None
    last_modified: Optional[datetime] = None
    # The source's own name for the data (a data.gouv.fr dataset's title).
    title: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "connector": self.connector,
            "url": self.url,
            "resource_id": self.resource_id,
            "fetched_at": self.fetched_at.isoformat(),
            "sha256": self.sha256,
            "bytes": self.bytes,
            "licence": self.licence,
            "licence_url": self.licence_url,
            "producer": self.producer,
            "title": self.title,
            "last_modified": (
                self.last_modified.isoformat() if self.last_modified else None
            ),
        }


@dataclass
class FetchResult:
    files: List[Path]
    format: str
    # delimiter, encoding, sheet, json_path…: how the engine reads the files.
    options: Dict[str, Any]
    provenance: Provenance
    # What the source itself says identifies this version (a checksum, a
    # modification date and size); the file's SHA-256 when it says nothing.
    version: Optional[str] = None
    # What the reviewer should know: a limit that stopped the fetch early…
    warnings: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class Limits:
    max_bytes: int
    timeout_s: float = 300.0


@dataclass
class Candidate:
    """One result of a connector's search (``discover``)."""

    title: str
    config: Dict[str, Any]
    description: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


class SourceConnector(Protocol):
    kind: str
    config_model: Type[BaseModel]

    def spec(self, locale: str) -> ConnectorSpec: ...

    async def fetch(
        self,
        owner_id: str,
        source_id: str,
        config: Dict[str, Any],
        creds: Credentials,
        dest: Path,
        limits: Limits,
    ) -> FetchResult: ...

    def fingerprint(self, result: FetchResult) -> str: ...


def sha256_of(paths: List[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    return digest.hexdigest()
