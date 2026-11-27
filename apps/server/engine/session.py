"""One sandboxed DuckDB connection per run (ADR 0003).

The connection can read and write the run's folder only
(``allowed_directories`` + ``enable_external_access=false``), loads no
extension it doesn't ship with, and its configuration is locked before any
query runs: no step can read ``/etc/passwd``, ``ATTACH`` a database, ``INSTALL``
an extension or raise its own memory limit. Every query runs under a
wall-clock timeout that interrupts the connection.
"""

import logging
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Generator, List, Optional, TypeVar

import duckdb

from server.core.config import config

logger = logging.getLogger(__name__)

T = TypeVar("T")


class EngineError(ValueError):
    """What went wrong, in words for the user (translated by the API)."""


def quote_ident(name: str) -> str:
    """A SQL identifier, quoted: the only way a column name reaches SQL."""
    return '"' + name.replace('"', '""') + '"'


def quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class EngineSession:
    """A DuckDB connection confined to ``run_dir``."""

    def __init__(
        self,
        run_dir: Path,
        *,
        memory_limit: Optional[str] = None,
        threads: Optional[int] = None,
        timeout_s: Optional[float] = None,
    ) -> None:
        self.run_dir = Path(run_dir).resolve()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        temp = self.run_dir / "tmp"
        temp.mkdir(exist_ok=True)
        self.timeout_s = timeout_s if timeout_s is not None else config.engine_timeout_s
        self.conn = duckdb.connect(
            database=":memory:",
            config={
                "memory_limit": memory_limit or config.engine_memory_limit,
                "threads": str(threads or config.engine_threads),
                "temp_directory": str(temp),
                "autoinstall_known_extensions": "false",
                "autoload_known_extensions": "false",
                "allow_community_extensions": "false",
            },
        )
        # The trailing slash: the run's folder and what is inside, nothing next to it.
        self.conn.execute(
            "SET allowed_directories = [" + quote_literal(f"{self.run_dir}/") + "]"
        )
        self.conn.execute("SET enable_external_access = false")
        self.conn.execute("SET lock_configuration = true")

    def path(self, *parts: str) -> Path:
        target = self.run_dir.joinpath(*parts).resolve()
        if self.run_dir not in (target, *target.parents):
            raise EngineError("A path outside the run's folder")
        return target

    def _guarded(self, fn: Callable[[], T]) -> T:
        timer = threading.Timer(self.timeout_s, self.conn.interrupt)
        timer.daemon = True
        timer.start()
        try:
            return fn()
        except duckdb.InterruptException:
            raise EngineError(
                f"The data took longer than {int(self.timeout_s)} s to process"
            ) from None
        except duckdb.OutOfMemoryException:
            raise EngineError(
                "Out of memory: try a filter step, or fewer columns"
            ) from None
        finally:
            timer.cancel()

    def execute(self, sql: str, params: Optional[List[Any]] = None) -> None:
        self._guarded(lambda: self.conn.execute(sql, params or []))

    def fetchall(self, sql: str, params: Optional[List[Any]] = None) -> List[tuple]:
        return self._guarded(lambda: self.conn.execute(sql, params or []).fetchall())

    def fetchone(self, sql: str, params: Optional[List[Any]] = None) -> Optional[tuple]:
        return self._guarded(lambda: self.conn.execute(sql, params or []).fetchone())

    def close(self) -> None:
        try:
            self.conn.close()
        except duckdb.Error:  # pragma: no cover — closing twice
            pass


@contextmanager
def session(run_dir: Path, **kwargs: Any) -> Generator[EngineSession, None, None]:
    s = EngineSession(run_dir, **kwargs)
    try:
        yield s
    finally:
        s.close()
