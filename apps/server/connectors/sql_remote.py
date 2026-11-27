"""The remote SQL connector (#322): a table of the user's own PostgreSQL
database, read-only, from a host an admin allowed.

The riskiest connector, so it does little and checks much:

- **Where.** The host must be in the platform's ``allowed_sql_hosts`` (empty:
  the connector refuses every host) and resolve to public addresses only
  (core/net.py). The connection goes to the address that was checked
  (``hostaddr``), the name kept for TLS: a DNS answer that changes between
  the check and the connection cannot point it elsewhere.
- **How.** TLS with the certificate verified against the system's roots
  (``sslmode=verify-full``); a read-only session
  (``default_transaction_read_only``) and a ``statement_timeout``; a short
  connect timeout.
- **What.** One table and its columns, named, never SQL: identifiers are
  quoted by psycopg, the row cap is a ``LIMIT``. Rows are streamed in batches
  from a server-side cursor into Parquet.
- **Credentials.** The password is the data source's secret
  (``source_db_password:<id>``), never in its config, a log or an error.
"""

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from pydantic import BaseModel, Field, field_validator

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

KIND = "sql_remote"
SECRET_PREFIX = "source_db_password:"  # noqa: S105 — a secret kind, not a secret
BATCH = 5_000
_NAME = r"^[A-Za-z_][A-Za-z0-9_$]{0,62}$"


def secret_kind(source_id: str) -> str:
    return f"{SECRET_PREFIX}{source_id}"


class SqlRemoteConfig(BaseModel):
    host: str = Field(..., min_length=1, max_length=253)
    port: int = Field(5432, ge=1, le=65535)
    database: str = Field(..., pattern=_NAME)
    user: str = Field(..., pattern=_NAME)
    schema_name: str = Field("public", pattern=_NAME, alias="schema")
    table: str = Field(..., pattern=_NAME)
    # The columns read (blank: every column).
    columns: List[str] = Field(default_factory=list, max_length=200)
    max_rows: int = Field(100_000, ge=1, le=1_000_000)
    statement_timeout_s: int = Field(60, ge=1, le=300)

    model_config = {"populate_by_name": True}

    @field_validator("host")
    @classmethod
    def _host(cls, host: str) -> str:
        host = host.strip().rstrip(".").lower()
        if not re.fullmatch(r"[a-z0-9.-]+", host):
            raise ValueError("a host name, without a scheme or a port")
        return host

    @field_validator("columns")
    @classmethod
    def _columns(cls, columns: List[str]) -> List[str]:
        for column in columns:
            if not re.fullmatch(_NAME, column):
                raise ValueError(f"'{column}' is not a column name")
        return columns


def _target(cfg: SqlRemoteConfig):
    """The checked, all-public address of an allowed host."""
    from server.core.net import UnsafeURLError, check_target_sync
    from server.services.platform import allowed_sql_hosts

    allowed = allowed_sql_hosts()
    if not allowed:
        raise ConnectorError(
            "No database host is allowed on this server: an admin adds it "
            "under Platform (allowed_sql_hosts)"
        )
    try:
        # The scheme only says "encrypted": the connection itself requires TLS.
        return check_target_sync(cfg.host, cfg.port, "https", allowed_hosts=allowed)
    except UnsafeURLError as exc:
        raise ConnectorError(str(exc)) from None


def _connect(cfg: SqlRemoteConfig, password: str):
    import psycopg

    target = _target(cfg)
    options = (
        "-c default_transaction_read_only=on "
        f"-c statement_timeout={cfg.statement_timeout_s * 1000} "
        "-c idle_in_transaction_session_timeout=60000"
    )
    try:
        conn = psycopg.connect(
            host=target.host,
            hostaddr=target.addresses[0],
            port=cfg.port,
            dbname=cfg.database,
            user=cfg.user,
            password=password,
            sslmode="verify-full",
            sslrootcert="system",
            connect_timeout=10,
            options=options,
            application_name="dataset-generator",
        )
    except psycopg.Error as exc:
        raise ConnectorError(_safe(exc, password)) from None
    conn.read_only = True
    return conn


def _safe(exc: Exception, password: str) -> str:
    """The driver's message, its first line, without the password."""
    message = (str(exc).strip().splitlines() or ["the connection failed"])[0]
    if password:
        message = message.replace(password, "***")
    return f"The database refused: {message[:200]}"


def _query(cfg: SqlRemoteConfig, limit: int):
    from psycopg import sql

    columns = (
        sql.SQL(", ").join(sql.Identifier(c) for c in cfg.columns)
        if cfg.columns
        else sql.SQL("*")
    )
    return sql.SQL("SELECT {} FROM {}.{} LIMIT {}").format(
        columns,
        sql.Identifier(cfg.schema_name),
        sql.Identifier(cfg.table),
        sql.Literal(limit),
    )


def _password(owner_id: str, source_id: str) -> str:
    from server.services.user_secrets import get_source_secret

    password = get_source_secret(owner_id, secret_kind(source_id))
    if not password:
        raise ConnectorError(
            "The database password is not saved: add it to the data source"
        )
    return password


def _jsonable(value: Any) -> Any:
    from decimal import Decimal

    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (dict, list)):
        import json

        return json.dumps(value, ensure_ascii=False, default=str)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    return value


def read_rows(
    cfg: SqlRemoteConfig,
    password: str,
    target: Path,
    limit: int,
    deadline_s: float,
    max_bytes: int = 1024**3,
) -> int:
    """The table's first ``limit`` rows into Parquet at ``target``; how many.
    Stops with an error past ``deadline_s`` or ``max_bytes`` of rows read."""
    import time

    import pyarrow as pa
    import pyarrow.parquet as pq
    import psycopg

    started = time.monotonic()
    conn = _connect(cfg, password)
    writer = None
    count = read = 0
    try:
        with conn.transaction(), conn.cursor(name="dataset_generator_read") as cur:
            cur.itersize = BATCH
            try:
                cur.execute(_query(cfg, limit))
                while True:
                    if time.monotonic() - started > deadline_s:
                        raise ConnectorError("The table took too long to read")
                    rows = cur.fetchmany(BATCH)
                    if not rows:
                        break
                    names = [d.name for d in cur.description or []]
                    table = pa.Table.from_pylist(
                        [
                            {n: _jsonable(v) for n, v in zip(names, row, strict=True)}
                            for row in rows
                        ]
                    )
                    if writer is None:
                        writer = pq.ParquetWriter(
                            target, table.schema, compression="zstd"
                        )
                    elif table.schema != writer.schema:
                        table = table.cast(writer.schema)
                    read += table.nbytes
                    if read > max_bytes:
                        raise ConnectorError(
                            f"More than {max_bytes // 1024**2} MB of rows: "
                            "lower max_rows or pick fewer columns"
                        )
                    writer.write_table(table)
                    count += len(rows)
            except psycopg.Error as exc:
                raise ConnectorError(_safe(exc, password)) from None
    finally:
        if writer is not None:
            writer.close()
        conn.close()
    if count == 0:
        raise ConnectorError("The table has no row")
    return count


class SqlRemoteConnector:
    kind = KIND
    config_model = SqlRemoteConfig

    def spec(self, locale: str) -> ConnectorSpec:
        return ConnectorSpec(
            kind=KIND,
            title=tr(locale, "connectors.sql_remote.title", "PostgreSQL database"),
            description=tr(
                locale,
                "connectors.sql_remote.description",
                "A table of your own PostgreSQL database, read-only, on a host an admin allowed",
            ),
            config_schema=SqlRemoteConfig.model_json_schema(by_alias=True),
            secret_kind=SECRET_PREFIX + "<data_source_id>",
        )

    async def test(
        self, owner_id: str, source_id: str, config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """The table's first 20 rows and its columns (the "Test" button)."""
        import asyncio
        import tempfile

        import pyarrow.parquet as pq

        cfg = SqlRemoteConfig.model_validate(config)
        password = await asyncio.to_thread(_password, owner_id, source_id)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "sample.parquet"
            await asyncio.to_thread(read_rows, cfg, password, target, 20, 60.0)
            table = pq.read_table(target)
        sample = table.to_pylist()
        return {"records": len(sample), "columns": table.column_names, "sample": sample}

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

        cfg = SqlRemoteConfig.model_validate(config)
        password = await asyncio.to_thread(_password, owner_id, source_id)
        await asyncio.to_thread(dest.mkdir, parents=True, exist_ok=True)
        target = dest / "table.parquet"
        count = await asyncio.to_thread(
            read_rows,
            cfg,
            password,
            target,
            cfg.max_rows + 1,
            limits.timeout_s,
            limits.max_bytes,
        )
        warnings: List[str] = []
        if count > cfg.max_rows:
            # One row past the cap says the table goes on: keep the cap.
            import pyarrow.parquet as pq

            table = pq.read_table(target).slice(0, cfg.max_rows)
            pq.write_table(table, target, compression="zstd")
            warnings.append(f"Stopped at {cfg.max_rows} rows (max_rows)")
        return FetchResult(
            files=[target],
            format="parquet",
            options={},
            provenance=Provenance(
                connector=KIND,
                fetched_at=datetime.now(timezone.utc),
                sha256=sha256_of([target]),
                bytes=target.stat().st_size,
                # Where it came from, without the user or the password.
                resource_id=f"{cfg.host}/{cfg.database}/{cfg.schema_name}.{cfg.table}",
            ),
            warnings=warnings,
        )

    def fingerprint(self, result: FetchResult) -> str:
        return f"sha256:{result.provenance.sha256}"
