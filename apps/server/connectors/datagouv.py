"""data.gouv.fr: search the national catalogue, fetch a resource with its
licence and producer (ADR 0001).

Two ways to read a resource:

- ``file`` (default): download the resource's file — hosted on data.gouv.fr,
  its redirects followed to the data.gouv.fr hosts only — and read it like an
  upload, with the tabular API's profile (encoding, separator) as the default
  reading options;
- ``tabular_api``: page through the tabular API's rows (200 a page), with
  server-side filters, into JSON Lines: a subset of a huge resource.

The licence is the dataset's (``lov2``, ``odc-odbl``…, mapped by
hub/licences.py), the producer its organisation, the fingerprint the
resource's checksum (else its last modification and size, else the file's
SHA-256).
"""

import asyncio
import gzip
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from server.connectors import http
from server.connectors.base import (
    Candidate,
    ConnectorError,
    ConnectorSpec,
    FetchResult,
    Limits,
    Provenance,
    sha256_of,
)
from server.connectors.sniff import sniff
from server.core.i18n import tr
from server.services.credentials import Credentials

KIND = "datagouv"
CATALOGUE = "https://www.data.gouv.fr/api/1"
TABULAR = "https://tabular-api.data.gouv.fr/api"
# The hosts this connector reaches (redirects included).
HOSTS = (
    "www.data.gouv.fr",
    "data.gouv.fr",
    "static.data.gouv.fr",
    "tabular-api.data.gouv.fr",
)
WHAT = "data.gouv.fr"
FORMATS = ("csv", "csv.gz", "tsv", "json", "jsonl", "parquet", "xlsx")
PAGE_SIZE = 200
MAX_PAGES = 500
FILTER_OPS = ("exact", "differs", "contains", "in", "less", "greater")


class TabularFilter(BaseModel):
    column: str = Field(..., min_length=1, max_length=200)
    op: Literal["exact", "differs", "contains", "in", "less", "greater"] = "exact"
    value: str = Field(..., max_length=500)


class DatagouvConfig(BaseModel):
    dataset_id: str = Field(..., pattern=r"^[A-Za-z0-9-]{1,64}$")
    resource_id: str = Field(..., pattern=r"^[A-Za-z0-9-]{1,64}$")
    mode: Literal["file", "tabular_api"] = "file"
    filters: List[TabularFilter] = Field(default_factory=list, max_length=20)
    max_pages: int = Field(MAX_PAGES, ge=1, le=MAX_PAGES)


def _parse_time(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _tabular(resource: Dict[str, Any]) -> bool:
    """The catalogue says the tabular API parsed this resource."""
    extras = resource.get("extras") or {}
    return bool(extras.get("analysis:parsing:parsing_table")) and not extras.get(
        "analysis:parsing:error"
    )


def _resource_view(resource: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": resource.get("id"),
        "title": resource.get("title"),
        "format": (resource.get("format") or "").lower(),
        "filesize": resource.get("filesize"),
        "last_modified": resource.get("last_modified"),
        "tabular_api": _tabular(resource),
        "hosted": http._host(resource.get("url") or "") in HOSTS,
    }


def _dataset_candidate(dataset: Dict[str, Any]) -> Optional[Candidate]:
    resources = [
        _resource_view(r)
        for r in dataset.get("resources") or []
        if (r.get("format") or "").lower() in FORMATS
    ]
    if not resources:
        return None
    org = dataset.get("organization") or {}
    return Candidate(
        title=dataset.get("title") or dataset.get("id") or "",
        description=(dataset.get("description") or "")[:300],
        config={"dataset_id": dataset.get("id")},
        extra={
            "dataset_id": dataset.get("id"),
            "page": dataset.get("page"),
            "organization": org.get("name"),
            "licence": dataset.get("license"),
            "last_update": dataset.get("last_update"),
            "resources": resources,
        },
    )


class DatagouvConnector:
    kind = KIND
    config_model = DatagouvConfig

    def spec(self, locale: str) -> ConnectorSpec:
        return ConnectorSpec(
            kind=KIND,
            title=tr(locale, "connectors.datagouv.title", "data.gouv.fr"),
            description=tr(
                locale,
                "connectors.datagouv.description",
                "A resource of the French national open data catalogue, with its "
                "licence and producer",
            ),
            config_schema=DatagouvConfig.model_json_schema(),
        )

    async def discover(self, query: str, creds: Credentials) -> List[Candidate]:
        data, _ = await http.get_json(
            f"{CATALOGUE}/datasets/",
            params={"q": query, "page_size": 20},
            allowed_hosts=HOSTS,
            what=WHAT,
        )
        out = []
        for dataset in (data or {}).get("data") or []:
            candidate = _dataset_candidate(dataset)
            if candidate is not None:
                out.append(candidate)
        return out

    async def profile(self, resource_id: str) -> Dict[str, Any]:
        """The tabular API's profile of a resource (header, types, encoding)."""
        data, _ = await http.get_json(
            f"{TABULAR}/resources/{resource_id}/profile/",
            allowed_hosts=HOSTS,
            what="The data.gouv.fr tabular API",
        )
        return (data or {}).get("profile") or {}

    async def _dataset(self, dataset_id: str) -> Dict[str, Any]:
        data, _ = await http.get_json(
            f"{CATALOGUE}/datasets/{dataset_id}/", allowed_hosts=HOSTS, what=WHAT
        )
        return data or {}

    async def fetch(
        self,
        owner_id: str,
        source_id: str,
        config: Dict[str, Any],
        creds: Credentials,
        dest: Path,
        limits: Limits,
    ) -> FetchResult:
        cfg = DatagouvConfig.model_validate(config)
        dataset = await self._dataset(cfg.dataset_id)
        resource = next(
            (
                r
                for r in dataset.get("resources") or []
                if r.get("id") == cfg.resource_id
            ),
            None,
        )
        if resource is None:
            raise ConnectorError(
                "This resource is no longer in the dataset on data.gouv.fr"
            )
        await asyncio.to_thread(dest.mkdir, parents=True, exist_ok=True)
        if cfg.mode == "tabular_api":
            path, fmt, options = await self._fetch_tabular(cfg, dest, limits)
        else:
            path, fmt, options = await self._fetch_file(resource, dest, limits)
        org = dataset.get("organization") or {}
        return FetchResult(
            files=[path],
            format=fmt,
            options=options,
            provenance=Provenance(
                connector=KIND,
                fetched_at=datetime.now(timezone.utc),
                sha256=sha256_of([path]),
                bytes=path.stat().st_size,
                url=dataset.get("page"),
                resource_id=cfg.resource_id,
                licence=dataset.get("license"),
                producer=org.get("name") or (dataset.get("owner") or {}).get("slug"),
                last_modified=_parse_time(resource.get("last_modified")),
                title=dataset.get("title"),
            ),
            version=_version(resource, cfg),
        )

    async def _fetch_file(self, resource: Dict[str, Any], dest: Path, limits: Limits):
        url = resource.get("url") or ""
        if http._host(url) not in HOSTS:
            raise ConnectorError(
                "This resource is hosted outside data.gouv.fr: add it with its URL instead"
            )
        fmt = (resource.get("format") or "").lower()
        if fmt not in FORMATS:
            raise ConnectorError(
                f"The {fmt or 'unknown'} format is not read: pick a CSV, JSON, Parquet or XLSX resource"
            )
        name = "resource." + ("csv.gz" if fmt == "csv.gz" else fmt)
        path, _ = await http.download(
            url, dest / name, max_bytes=limits.max_bytes, allowed_hosts=HOSTS, what=WHAT
        )
        if fmt == "csv.gz":
            path = _gunzip(path, dest / "resource.csv", limits.max_bytes)
            fmt = "csv"
        hints: Dict[str, Any] = {}
        if fmt in ("csv", "tsv") and _tabular(resource):
            try:
                profile = await self.profile(str(resource.get("id")))
                hints = _hints(profile)
            except ConnectorError:
                hints = {}  # the profile only helps: the file is read anyway
        sniffed = sniff(path, path.name, {"format": fmt, **hints})
        return path, sniffed.format, sniffed.options

    async def _fetch_tabular(self, cfg: DatagouvConfig, dest: Path, limits: Limits):
        params: Dict[str, Any] = {"page_size": PAGE_SIZE}
        for f in cfg.filters:
            params[f"{f.column}__{f.op}"] = f.value
        target = dest / "rows.jsonl"
        written = 0
        url: Optional[str] = f"{TABULAR}/resources/{cfg.resource_id}/data/"
        page = 0
        with target.open("w", encoding="utf-8") as out:
            while url and page < cfg.max_pages:
                page += 1
                data, _ = await http.get_json(
                    url,
                    params=params if page == 1 else None,
                    allowed_hosts=HOSTS,
                    what="The data.gouv.fr tabular API",
                )
                for row in (data or {}).get("data") or []:
                    row.pop("__id", None)
                    line = json.dumps(row, ensure_ascii=False) + "\n"
                    written += len(line.encode())
                    if written > limits.max_bytes:
                        raise ConnectorError(
                            f"More than {limits.max_bytes // 1024**2} MB of rows: add a filter"
                        )
                    out.write(line)
                url = ((data or {}).get("links") or {}).get("next")
        if written == 0:
            raise ConnectorError("The tabular API gave no row (check the filters)")
        return target, "jsonl", {}

    async def unchanged(
        self,
        owner_id: str,
        source_id: str,
        config: Dict[str, Any],
        version: Optional[str],
    ) -> bool:
        """Whether the resource is still ``version``: one catalogue call (its
        checksum, or last modification and size), no download."""
        if not version:
            return False
        cfg = DatagouvConfig.model_validate(config)
        dataset = await self._dataset(cfg.dataset_id)
        resource = next(
            (
                r
                for r in dataset.get("resources") or []
                if r.get("id") == cfg.resource_id
            ),
            None,
        )
        return resource is not None and _version(resource, cfg) == version

    def fingerprint(self, result: FetchResult) -> str:
        return result.version or result.provenance.sha256


def _version(resource: Dict[str, Any], cfg: DatagouvConfig) -> Optional[str]:
    """The resource's checksum, else its last modification and size; the
    filters too in tabular mode (another subset is another version)."""
    checksum = resource.get("checksum") or {}
    if checksum.get("value"):
        base = f"{checksum.get('type', 'sha1')}:{checksum['value']}"
    elif resource.get("last_modified") and resource.get("filesize"):
        base = f"{resource['last_modified']}/{resource['filesize']}"
    else:
        return None
    if cfg.mode == "tabular_api":
        base += "|" + json.dumps([f.model_dump() for f in cfg.filters], sort_keys=True)
    return base


def _hints(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Reading options from the tabular API's profile."""
    hints: Dict[str, Any] = {}
    encoding = str(profile.get("encoding") or "").strip().lower()
    if encoding:
        hints["encoding"] = {"utf-8-sig": "utf-8-sig", "utf-8": "utf-8"}.get(
            encoding, encoding.replace("_", "-")
        )
    separator = profile.get("separator")
    if isinstance(separator, str) and len(separator) == 1:
        hints["delimiter"] = separator
    return hints


def _gunzip(path: Path, target: Path, max_bytes: int) -> Path:
    written = 0
    try:
        with gzip.open(path, "rb") as src, target.open("wb") as out:
            while chunk := src.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise ConnectorError(
                        f"The file is larger than {max_bytes // 1024**2} MB once unzipped"
                    )
                out.write(chunk)
    except (OSError, EOFError):
        target.unlink(missing_ok=True)
        raise ConnectorError("The .csv.gz file can't be unzipped") from None
    path.unlink(missing_ok=True)
    return target


__all__ = ["DatagouvConnector", "HOSTS", "KIND"]
