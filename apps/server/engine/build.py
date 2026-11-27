"""A fetched data source, through the engine, to the draft's files and metadata."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from server.connectors.base import FetchResult
from server.engine.load import TABLE, load
from server.engine.profile import profile, write_parquet
from server.engine.session import EngineSession, session


@dataclass
class Built:
    rows: int
    schema: List[Dict[str, str]]
    profile: Dict[str, Any]
    data_path: Path
    data_bytes: int

    def metadata(self) -> Dict[str, Any]:
        """What ``job_runs.draft`` keeps: never the rows."""
        return {
            "rows": self.rows,
            "schema": self.schema,
            "profile": self.profile,
            "data_path": self.data_path.name,
            "data_bytes": self.data_bytes,
        }


def build_in(s: EngineSession, result: FetchResult, data_path: Path) -> Built:
    loaded = load(s, result)
    size = write_parquet(s, TABLE, data_path)
    return Built(
        rows=loaded.rows,
        schema=loaded.schema(),
        profile=profile(s, TABLE),
        data_path=data_path,
        data_bytes=size,
    )


def build(run_dir: Path, result: FetchResult) -> Built:
    """Load ``result`` in a sandboxed session on ``run_dir`` and write
    ``run_dir/data.parquet``. Blocking: run it in a worker thread."""
    with session(run_dir) as s:
        return build_in(s, result, Path(run_dir) / "data.parquet")
