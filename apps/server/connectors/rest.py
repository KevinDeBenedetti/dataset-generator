"""A REST API's JSON pages as rows (ADR 0001): one GET endpoint, how to page
through it, where the records are.

Requests go through ``core/net.py`` (connectors/http.py): https, public
addresses, redirects to the same site only, ``Retry-After`` and backoff on 429
and 503. The API key, when there is one, is the data source's secret
(``source_api_key:<data_source_id>``), sent as a header or a query parameter —
never logged, never in an error, the provenance or the card. Records are
flattened one level (``parent.child`` columns, deeper values and arrays as JSON
text) into JSON Lines for the engine. ``max_pages`` and ``max_records`` stop
the fetch with a warning, not a failure.
"""

import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, TextIO, Tuple, cast
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator

from server.connectors import http
from server.connectors.base import (
    ConnectorError,
    ConnectorSpec,
    FetchResult,
    Limits,
    Provenance,
    sha256_of,
)
from server.core.i18n import tr
from server.services.credentials import Credentials

KIND = "rest"
SECRET_PREFIX = "source_api_key:"  # noqa: S105 — a kind's prefix, not a value
_PATH = re.compile(r"^\$(?:\.[A-Za-z0-9_@$-]+|\[\d+\])*$")
_STEP = re.compile(r"\.([A-Za-z0-9_@$-]+)|\[(\d+)\]")


def _check_path(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip() or "$"
    if not _PATH.match(value):
        raise ValueError("a path looks like $.results or $.data[0].items")
    return value


def json_path(document: Any, path: str) -> Any:
    """``$.a.b[0].c`` in ``document`` (None when a step is missing)."""
    node = document
    for name, index in _STEP.findall(path[1:]):
        if name:
            if not isinstance(node, dict) or name not in node:
                return None
            node = node[name]
        else:
            i = int(index)
            if not isinstance(node, list) or i >= len(node):
                return None
            node = node[i]
    return node


class Auth(BaseModel):
    type: Literal["none", "header", "query"] = "none"
    name: Optional[str] = Field(None, pattern=r"^[A-Za-z0-9_-]{1,64}$")

    @model_validator(mode="after")
    def _named(self) -> "Auth":
        if self.type != "none" and not self.name:
            raise ValueError("auth.name: the header or parameter name is needed")
        return self


class Pagination(BaseModel):
    type: Literal["none", "page", "offset", "cursor", "link_header", "next_url"] = (
        "none"
    )
    page_param: str = Field("page", max_length=64)
    start_page: int = Field(1, ge=0, le=1)
    size_param: Optional[str] = Field(None, max_length=64)
    size: int = Field(100, ge=1, le=10_000)
    offset_param: str = Field("offset", max_length=64)
    cursor_path: Optional[str] = None
    cursor_param: str = Field("cursor", max_length=64)
    next_url_path: Optional[str] = None

    @field_validator("cursor_path", "next_url_path")
    @classmethod
    def _paths(cls, value: Optional[str]) -> Optional[str]:
        return _check_path(value)

    @model_validator(mode="after")
    def _complete(self) -> "Pagination":
        if self.type == "cursor" and not self.cursor_path:
            raise ValueError("pagination.cursor_path is needed for a cursor")
        if self.type == "next_url" and not self.next_url_path:
            raise ValueError("pagination.next_url_path is needed")
        return self


class RestConfig(BaseModel):
    url: str = Field(..., max_length=2000)
    params: Dict[str, str] = Field(default_factory=dict, max_length=50)
    auth: Auth = Field(default_factory=Auth)
    records_path: str = "$"
    total_path: Optional[str] = None
    pagination: Pagination = Field(default_factory=Pagination)
    max_pages: int = Field(200, ge=1, le=1000)
    max_records: int = Field(1_000_000, ge=1, le=10_000_000)
    rate_limit_per_s: float = Field(5.0, gt=0, le=50)
    producer: Optional[str] = Field(None, max_length=200)
    # The ready-made preset this config came from (connectors/presets): its
    # rate limit and depth cap hold even when the config is edited.
    preset: Optional[str] = Field(None, max_length=64)

    @model_validator(mode="after")
    def _preset_limits(self) -> "RestConfig":
        if self.preset is None:
            return self
        from server.connectors.presets import get_preset

        preset = get_preset(self.preset)
        if preset is None:
            raise ValueError(f"unknown preset '{self.preset}'")
        self.rate_limit_per_s = min(self.rate_limit_per_s, preset.rate_limit_per_s)
        if preset.max_records is not None:
            self.max_records = min(self.max_records, preset.max_records)
        return self

    @field_validator("url")
    @classmethod
    def _https(cls, url: str) -> str:
        parts = urlsplit(url.strip())
        if parts.scheme.lower() != "https" or not parts.hostname:
            raise ValueError("only https URLs are called")
        if parts.username or parts.password:
            raise ValueError("no credentials in the URL: use the API key")
        return url.strip()

    @field_validator("params")
    @classmethod
    def _plain_params(cls, params: Dict[str, Any]) -> Dict[str, str]:
        return {str(k): str(v) for k, v in params.items()}

    @field_validator("records_path")
    @classmethod
    def _records(cls, value: str) -> str:
        return _check_path(value) or "$"

    @field_validator("total_path")
    @classmethod
    def _total(cls, value: Optional[str]) -> Optional[str]:
        return _check_path(value)


def secret_kind(source_id: str) -> str:
    return SECRET_PREFIX + source_id


def flatten(record: Any) -> Dict[str, Any]:
    """One level: ``{"a": {"b": 1}}`` → ``{"a.b": 1}``; deeper objects and
    arrays as JSON text. A record that is not an object is ``{"value": …}``."""
    if not isinstance(record, dict):
        return {
            "value": record
            if not isinstance(record, (list, dict))
            else json.dumps(record, ensure_ascii=False)
        }
    out: Dict[str, Any] = {}
    for key, value in record.items():
        if isinstance(value, dict):
            for sub, inner in value.items():
                out[f"{key}.{sub}"] = (
                    json.dumps(inner, ensure_ascii=False)
                    if isinstance(inner, (dict, list))
                    else inner
                )
        elif isinstance(value, list):
            out[key] = json.dumps(value, ensure_ascii=False)
        else:
            out[key] = value
    return out


def _next_link(header: str) -> Optional[str]:
    """The ``rel="next"`` URL of a ``Link`` header."""
    for part in header.split(","):
        url, _, rest = part.partition(";")
        if re.search(r'rel\s*=\s*"?next"?', rest):
            return url.strip().strip("<>")
    return None


class RestConnector:
    kind = KIND
    config_model = RestConfig

    def spec(self, locale: str) -> ConnectorSpec:
        return ConnectorSpec(
            kind=KIND,
            title=tr(locale, "connectors.rest.title", "REST API"),
            description=tr(
                locale,
                "connectors.rest.description",
                "The JSON pages of one GET endpoint: where the records are and "
                "how to page through them",
            ),
            config_schema=RestConfig.model_json_schema(),
            secret_kind=SECRET_PREFIX + "<data_source_id>",
        )

    def _auth(
        self, owner_id: str, source_id: str, cfg: RestConfig
    ) -> Tuple[Dict[str, str], Dict[str, str]]:
        """(headers, params) carrying the API key."""
        if cfg.auth.type == "none":
            return {}, {}
        from server.services.user_secrets import get_source_secret

        key = get_source_secret(owner_id, secret_kind(source_id))
        if not key:
            raise ConnectorError("The API key is not saved: add it to the data source")
        name = cfg.auth.name or ""
        return ({name: key}, {}) if cfg.auth.type == "header" else ({}, {name: key})

    async def _pages(
        self,
        owner_id: str,
        source_id: str,
        cfg: RestConfig,
        *,
        max_pages: int,
        max_records: int,
        sink,
    ) -> Tuple[int, int, List[str], Optional[str]]:
        """Fetch the pages, ``sink(records)`` each; (pages, records, warnings,
        the first page's digest with the total when the API gives one)."""
        headers, secret_params = await asyncio.to_thread(
            self._auth, owner_id, source_id, cfg
        )
        what = urlsplit(cfg.url).hostname or "The API"
        p = cfg.pagination
        url: Optional[str] = cfg.url
        params: Dict[str, Any] = dict(cfg.params)
        if p.size_param:
            params[p.size_param] = p.size
        if p.type == "page":
            params[p.page_param] = p.start_page
        if p.type == "offset":
            params[p.offset_param] = 0
        pages = records = 0
        warnings: List[str] = []
        first_digest: Optional[str] = None
        delay = 1.0 / cfg.rate_limit_per_s
        while url:
            if pages >= max_pages:
                warnings.append(f"Stopped after {max_pages} pages (max_pages)")
                break
            if records >= max_records:
                # Asking for the next page anyway would be refused by APIs
                # that cap how deep paging goes (an offset + limit maximum).
                warnings.append(f"Stopped at {max_records} records (max_records)")
                break
            if pages:
                await asyncio.sleep(delay)
            query = (
                {**params, **secret_params}
                if params is not None
                else dict(secret_params)
            )
            data, answer = await http.get_json(
                url,
                params=query or None,
                headers=headers,
                what=what,
                redirect_ok=http.same_site,
            )
            pages += 1
            found = json_path(data, cfg.records_path)
            if found is None:
                found = []
            if not isinstance(found, list):
                found = [found]
            if pages == 1:
                total = json_path(data, cfg.total_path) if cfg.total_path else None
                first_digest = hashlib.sha256(
                    json.dumps(found, sort_keys=True, default=str).encode()
                ).hexdigest() + (f"|{total}" if total is not None else "")
            room = max_records - records
            if len(found) > room:
                found = found[:room]
                await asyncio.to_thread(sink, found)
                records += len(found)
                warnings.append(f"Stopped at {max_records} records (max_records)")
                break
            await asyncio.to_thread(sink, found)
            records += len(found)
            # The next page.
            if p.type == "none" or not found:
                break
            if p.type == "page":
                if len(found) < p.size and p.size_param:
                    break
                params = {**params, p.page_param: int(params[p.page_param]) + 1}
            elif p.type == "offset":
                if len(found) < p.size:
                    break
                params = {
                    **params,
                    p.offset_param: int(params[p.offset_param]) + len(found),
                }
            elif p.type == "cursor":
                cursor = json_path(data, p.cursor_path or "$")
                # No cursor, or the same one again: the last page (Sirene's way).
                if cursor in (None, "", False) or str(cursor) == str(
                    params.get(p.cursor_param)
                ):
                    break
                params = {**params, p.cursor_param: str(cursor)}
            elif p.type == "link_header":
                url = _next_link(answer.get("Link", ""))
                params = {}  # the next link carries its own query
            elif p.type == "next_url":
                nxt = json_path(data, p.next_url_path or "$")
                url = nxt if isinstance(nxt, str) and nxt else None
                params = {}
            if url and not http.same_site(cfg.url, url):
                raise ConnectorError(
                    f"{what} gave a next page on another site: refusing to follow"
                )
        return pages, records, warnings, first_digest

    async def test(
        self, owner_id: str, source_id: str, config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """The first page only: its records and columns (the "Test" button)."""
        cfg = RestConfig.model_validate(config)
        seen: List[Dict[str, Any]] = []
        await self._pages(
            owner_id,
            source_id,
            cfg,
            max_pages=1,
            max_records=cfg.max_records,
            sink=lambda found: seen.extend(flatten(r) for r in found),
        )
        columns: List[str] = []
        for row in seen:
            for key in row:
                if key not in columns:
                    columns.append(key)
        return {"records": len(seen), "columns": columns, "sample": seen[:20]}

    async def fetch(
        self,
        owner_id: str,
        source_id: str,
        config: Dict[str, Any],
        creds: Credentials,
        dest: Path,
        limits: Limits,
    ) -> FetchResult:
        cfg = RestConfig.model_validate(config)
        await asyncio.to_thread(dest.mkdir, parents=True, exist_ok=True)
        target = dest / "records.jsonl"
        written = {"bytes": 0}
        stream = cast(
            TextIO, await asyncio.to_thread(target.open, "w", encoding="utf-8")
        )

        def sink(found: List[Any]) -> None:
            for record in found:
                line = (
                    json.dumps(flatten(record), ensure_ascii=False, default=str) + "\n"
                )
                written["bytes"] += len(line.encode())
                if written["bytes"] > limits.max_bytes:
                    raise ConnectorError(
                        f"More than {limits.max_bytes // 1024**2} MB of records: lower max_records"
                    )
                stream.write(line)

        try:
            pages, records, warnings, digest = await self._pages(
                owner_id,
                source_id,
                cfg,
                max_pages=cfg.max_pages,
                max_records=cfg.max_records,
                sink=sink,
            )
        finally:
            stream.close()
        if records == 0:
            raise ConnectorError(
                "The API gave no record: check records_path and the parameters"
            )
        return FetchResult(
            files=[target],
            format="jsonl",
            options={},
            provenance=Provenance(
                connector=KIND,
                fetched_at=datetime.now(timezone.utc),
                sha256=sha256_of([target]),
                bytes=target.stat().st_size,
                # The endpoint and its plain parameters: never the API key.
                url=cfg.url,
                resource_id=json.dumps(cfg.params, sort_keys=True)
                if cfg.params
                else None,
                producer=cfg.producer,
            ),
            version=f"first:{digest}" if digest and cfg.total_path else None,
            warnings=warnings,
        )

    def fingerprint(self, result: FetchResult) -> str:
        return result.version or f"sha256:{result.provenance.sha256}"
