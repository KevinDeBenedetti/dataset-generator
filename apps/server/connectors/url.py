"""A file at a URL: the direct links of open data portals (ADR 0001).

Fetched through ``core/net.py`` only: https, public addresses (each request
resolved and pinned, so a DNS answer can't switch to a private address
between the check and the connection), a redirect followed only to the same
registrable domain, the upload limit streamed, 60 s timeout. The format comes
from ``Content-Type``, then the extension, then the first bytes; a ``.gz`` is
unzipped, a ``.zip`` holding one file is extracted under a size and ratio
guard. An optional header (``Authorization`` or another) is the data source's
own secret, stored write-only.

The fingerprint is a strong ``ETag``, else ``Last-Modified`` and
``Content-Length``, else the file's SHA-256; a refresh asks with
``If-None-Match`` / ``If-Modified-Since`` and a 304 means unchanged.
"""

import asyncio
import gzip
import zipfile
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

from server.connectors import http
from server.connectors.base import (
    ConnectorError,
    ConnectorSpec,
    FetchResult,
    Limits,
    Provenance,
    sha256_of,
)
from server.connectors.sniff import format_from_name, sniff
from server.core.i18n import tr
from server.services.credentials import Credentials

KIND = "url"
SECRET_PREFIX = "source_http_header:"  # noqa: S105 — a kind's prefix, not a value
# A compressed member may expand this many times, no more (a zip bomb doesn't).
MAX_RATIO = 100
_CONTENT_TYPES = {
    "text/csv": "csv",
    "application/csv": "csv",
    "text/tab-separated-values": "tsv",
    "application/json": "json",
    "application/geo+json": "json",
    "application/x-ndjson": "jsonl",
    "application/jsonl": "jsonl",
    "application/vnd.apache.parquet": "parquet",
    "application/x-parquet": "parquet",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/gzip": "gz",
    "application/x-gzip": "gz",
    "application/zip": "zip",
}


class UrlConfig(BaseModel):
    url: str = Field(..., max_length=2000)
    format: Optional[str] = Field(None, pattern=r"^(csv|tsv|json|jsonl|parquet|xlsx)$")
    delimiter: Optional[str] = Field(None, min_length=1, max_length=1)
    encoding: Optional[str] = Field(None, max_length=32)
    sheet: Optional[str] = Field(None, max_length=100)
    json_path: Optional[str] = Field(None, max_length=200)
    # The name of the header the data source's secret is sent in, if any.
    header_name: Optional[str] = Field(None, pattern=r"^[A-Za-z0-9-]{1,64}$")
    producer: Optional[str] = Field(None, max_length=200)

    @field_validator("url")
    @classmethod
    def _https(cls, url: str) -> str:
        parts = urlsplit(url.strip())
        if parts.scheme.lower() != "https" or not parts.hostname:
            raise ValueError("only https URLs are fetched")
        if parts.username or parts.password:
            raise ValueError("no credentials in the URL: use the secret header")
        return url.strip()


def secret_kind(source_id: str) -> str:
    return SECRET_PREFIX + source_id


def _strong_etag(value: str) -> Optional[str]:
    value = (value or "").strip()
    if not value or value.startswith("W/"):
        return None
    return value


def version_from(headers: Any) -> Optional[str]:
    """``etag:<tag>`` or ``lm:<Last-Modified>|<Content-Length>``, or None."""
    etag = _strong_etag(headers.get("ETag", ""))
    if etag:
        return f"etag:{etag}"
    modified = headers.get("Last-Modified")
    length = headers.get("Content-Length")
    if modified and length:
        return f"lm:{modified}|{length}"
    return None


def conditional_headers(version: Optional[str]) -> Dict[str, str]:
    """The headers asking whether ``version`` changed."""
    if not version:
        return {}
    if version.startswith("etag:"):
        return {"If-None-Match": version[5:]}
    if version.startswith("lm:"):
        return {"If-Modified-Since": version[3:].split("|", 1)[0]}
    return {}


def _format_hint(content_type: str, url: str) -> Optional[str]:
    base = (content_type or "").split(";")[0].strip().lower()
    if base in _CONTENT_TYPES:
        return _CONTENT_TYPES[base]
    path = urlsplit(url).path.lower()
    if path.endswith(".gz"):
        return "gz"
    if path.endswith(".zip"):
        return "zip"
    return format_from_name(path)


def _gunzip(path: Path, target: Path, max_bytes: int) -> Path:
    compressed = path.stat().st_size or 1
    written = 0
    try:
        with gzip.open(path, "rb") as src, target.open("wb") as out:
            while chunk := src.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes or written > compressed * MAX_RATIO:
                    raise ConnectorError(
                        "The compressed file expands too much: refusing it"
                    )
                out.write(chunk)
    except (OSError, EOFError):
        target.unlink(missing_ok=True)
        raise ConnectorError("The .gz file can't be unzipped") from None
    except ConnectorError:
        target.unlink(missing_ok=True)
        raise
    path.unlink(missing_ok=True)
    return target


def _unzip(path: Path, dest: Path, max_bytes: int) -> Path:
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise ConnectorError("The .zip file can't be read") from None
    with archive:
        members = [m for m in archive.infolist() if not m.is_dir()]
        if len(members) != 1:
            raise ConnectorError(
                f"The .zip file holds {len(members)} files: one is expected"
            )
        member = members[0]
        if member.file_size > max_bytes:
            raise ConnectorError(
                f"The file inside is larger than {max_bytes // 1024**2} MB"
            )
        if member.compress_size and member.file_size / member.compress_size > MAX_RATIO:
            raise ConnectorError("The compressed file expands too much: refusing it")
        name = PurePosixPath(member.filename).name or "file"
        target = dest / f"unzipped-{name}"
        written = 0
        with archive.open(member) as src, target.open("wb") as out:
            while chunk := src.read(1024 * 1024):
                written += len(chunk)
                # The header's sizes may lie: count what really comes out.
                if (
                    written > max_bytes
                    or written > (member.compress_size or 1) * MAX_RATIO
                ):
                    out.close()
                    target.unlink(missing_ok=True)
                    raise ConnectorError(
                        "The compressed file expands too much: refusing it"
                    )
                out.write(chunk)
    path.unlink(missing_ok=True)
    return target


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class UrlConnector:
    kind = KIND
    config_model = UrlConfig

    def spec(self, locale: str) -> ConnectorSpec:
        return ConnectorSpec(
            kind=KIND,
            title=tr(locale, "connectors.url.title", "File at a URL"),
            description=tr(
                locale,
                "connectors.url.description",
                "A direct https link to a CSV, TSV, JSON, Parquet or Excel file "
                "(.gz and single-file .zip unpacked)",
            ),
            config_schema=UrlConfig.model_json_schema(),
            secret_kind=SECRET_PREFIX + "<data_source_id>",
        )

    def _headers(self, owner_id: str, source_id: str, cfg: UrlConfig) -> Dict[str, str]:
        if not cfg.header_name:
            return {}
        from server.services.user_secrets import get_source_secret

        value = get_source_secret(owner_id, secret_kind(source_id))
        if not value:
            raise ConnectorError(
                f"The {cfg.header_name} header's value is not saved: add it to the data source"
            )
        return {cfg.header_name: value}

    async def unchanged(
        self,
        owner_id: str,
        source_id: str,
        config: Dict[str, Any],
        version: Optional[str],
    ) -> bool:
        """Whether the file is still ``version`` (a 304 to a conditional HEAD)."""
        cfg = UrlConfig.model_validate(config)
        ask = conditional_headers(version)
        if not ask:
            return False
        headers = await asyncio.to_thread(self._headers, owner_id, source_id, cfg)
        status, answer = await http.head(
            cfg.url,
            headers={**headers, **ask},
            what=_site(cfg.url),
            redirect_ok=http.same_site,
        )
        if status == 304:
            return True
        return status < 400 and version_from(answer) == version

    async def fetch(
        self,
        owner_id: str,
        source_id: str,
        config: Dict[str, Any],
        creds: Credentials,
        dest: Path,
        limits: Limits,
    ) -> FetchResult:
        cfg = UrlConfig.model_validate(config)
        headers = await asyncio.to_thread(self._headers, owner_id, source_id, cfg)
        await asyncio.to_thread(dest.mkdir, parents=True, exist_ok=True)
        path, answer = await http.download(
            cfg.url,
            dest / "download",
            max_bytes=limits.max_bytes,
            headers=headers,
            what=_site(cfg.url),
            redirect_ok=http.same_site,
        )
        hint = _format_hint(answer.get("Content-Type", ""), cfg.url)
        if hint == "gz":
            path = await asyncio.to_thread(
                _gunzip, path, dest / "download.unzipped", limits.max_bytes
            )
            inner = urlsplit(cfg.url).path.lower().removesuffix(".gz")
            hint = format_from_name(inner)
        elif await asyncio.to_thread(_is_zip, path):
            if await asyncio.to_thread(_is_xlsx, path):
                hint = "xlsx"  # an Excel workbook is a ZIP too
            else:
                path = await asyncio.to_thread(_unzip, path, dest, limits.max_bytes)
                hint = format_from_name(path.name)
        overrides = {
            "format": cfg.format or hint,
            "delimiter": cfg.delimiter,
            "encoding": cfg.encoding,
            "sheet": cfg.sheet,
            "json_path": cfg.json_path,
        }
        sniffed = sniff(path, path.name, overrides)
        return FetchResult(
            files=[path],
            format=sniffed.format,
            options=sniffed.options,
            provenance=Provenance(
                connector=KIND,
                fetched_at=datetime.now(timezone.utc),
                sha256=sha256_of([path]),
                bytes=path.stat().st_size,
                url=cfg.url,
                producer=cfg.producer,
                last_modified=_parse_date(answer.get("Last-Modified")),
            ),
            version=version_from(answer),
        )

    def fingerprint(self, result: FetchResult) -> str:
        return result.version or f"sha256:{result.provenance.sha256}"


def _site(url: str) -> str:
    return urlsplit(url).hostname or "The site"


def _is_zip(path: Path) -> bool:
    with path.open("rb") as stream:
        return stream.read(4) == b"PK\x03\x04"


def _is_xlsx(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            return any(n.startswith("xl/") for n in archive.namelist())
    except zipfile.BadZipFile:
        return False
