"""The upload connector: a CSV, TSV, JSON, JSONL, Parquet or XLSX file the user
sends (``POST /data-sources/upload``).

The file is streamed into the draft store under the data source's folder and
stays there until the data source is deleted. Its fingerprint is its SHA-256;
its licence is what the user states.
"""

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

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

KIND = "upload"


class UploadConfig(BaseModel):
    filename: str = Field(..., description="The file's name, as uploaded")
    stored_name: str = Field(..., description="Its name in the draft store")
    format: str
    options: Dict[str, Any] = Field(default_factory=dict)
    sha256: str
    bytes: int


def safe_name(filename: str) -> str:
    """A storage name for ``filename``: its last path part, plain characters."""
    base = Path(filename.replace("\\", "/")).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-.")
    return (cleaned or "file")[:120]


class UploadConnector:
    kind = KIND
    config_model = UploadConfig

    def spec(self, locale: str) -> ConnectorSpec:
        return ConnectorSpec(
            kind=KIND,
            title=tr(locale, "connectors.upload.title", "File upload"),
            description=tr(
                locale,
                "connectors.upload.description",
                "A CSV, TSV, JSON, JSONL, Parquet or Excel (.xlsx) file from your computer",
            ),
            config_schema=UploadConfig.model_json_schema(),
            created_by_upload=True,
        )

    async def fetch(
        self,
        owner_id: str,
        source_id: str,
        config: Dict[str, Any],
        creds: Credentials,
        dest: Path,
        limits: Limits,
    ) -> FetchResult:
        import asyncio

        cfg = UploadConfig.model_validate(config)
        target = await asyncio.to_thread(
            self._copy, owner_id, source_id, cfg, dest, limits
        )
        return FetchResult(
            files=[target],
            format=cfg.format,
            options=dict(cfg.options),
            provenance=Provenance(
                connector=KIND,
                fetched_at=datetime.now(timezone.utc),
                sha256=sha256_of([target]),
                bytes=target.stat().st_size,
                resource_id=cfg.filename,
            ),
        )

    @staticmethod
    def _copy(
        owner_id: str, source_id: str, cfg: UploadConfig, dest: Path, limits: Limits
    ) -> Path:
        from server.services.draft_store import SOURCES_DIR, get_store

        stored = get_store().path(owner_id, SOURCES_DIR, source_id, cfg.stored_name)
        if not stored.is_file():
            raise ConnectorError("The uploaded file is gone: upload it again")
        if stored.stat().st_size > limits.max_bytes:
            raise ConnectorError("The uploaded file is larger than allowed")
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / cfg.stored_name
        shutil.copyfile(stored, target)
        return target

    async def unchanged(
        self,
        owner_id: str,
        source_id: str,
        config: Dict[str, Any],
        version: Optional[str],
    ) -> bool:
        """An uploaded file never changes: another file is another data source."""
        return bool(version) and version == config.get("sha256")

    def fingerprint(self, result: FetchResult) -> str:
        return result.provenance.sha256


def describe(
    path: Path, filename: str, overrides: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """The upload's config once stored at ``path``: what the sniffing found."""
    from server.connectors.sniff import sniff

    sniffed = sniff(path, filename, overrides)
    if sniffed.format == "xlsx":
        _check_one_sheet(path, sniffed.options.get("sheet"))
    return UploadConfig(
        filename=Path(filename).name[:200] or "file",
        stored_name=path.name,
        format=sniffed.format,
        options=sniffed.options,
        sha256=sha256_of([path]),
        bytes=path.stat().st_size,
    ).model_dump()


def _sheet_names(path: Path) -> list:
    """The sheet names of a workbook, read from ``xl/workbook.xml`` without an
    XML parser (an uploaded file is untrusted: no entity expansion here)."""
    import html
    import zipfile

    with zipfile.ZipFile(path) as archive:
        try:
            info = archive.getinfo("xl/workbook.xml")
        except KeyError:
            raise ConnectorError("This Excel file has no workbook") from None
        if info.file_size > 1024 * 1024:
            raise ConnectorError("This Excel file's workbook is too large to read")
        text = archive.read(info).decode("utf-8", errors="replace")
    names = re.findall(r"<(?:\w+:)?sheet\b[^>]*?\bname=\"([^\"]*)\"", text)
    return [html.unescape(n) for n in names]


def _check_one_sheet(path: Path, sheet: Optional[str]) -> None:
    """A data source is one sheet: a workbook of several needs one named."""
    names = _sheet_names(path)
    if sheet:
        if sheet not in names:
            raise ConnectorError(
                f"No sheet '{sheet}' in this workbook (it has: {', '.join(names)})"
            )
    elif len(names) > 1:
        raise ConnectorError(
            "This workbook has several sheets: name the one to read "
            f"({', '.join(names)})"
        )
