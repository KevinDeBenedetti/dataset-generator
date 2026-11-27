"""Column profiles (engine/profile.py), against values computed by hand."""

import os
from datetime import datetime, timezone

import pytest

from server.connectors.base import FetchResult, Provenance
from server.engine.load import load
from server.engine.profile import preview_rows, profile, write_parquet
from server.engine.session import EngineError, session


def test_profile_matches_hand_computed_values(tmp_path):
    with session(tmp_path / "run") as s:
        s.execute(
            "CREATE TABLE t AS SELECT * FROM (VALUES "
            "(1, 'a', DATE '2026-01-01'), (2, 'b', DATE '2026-03-01'), "
            "(3, 'a', NULL), (NULL, 'a', DATE '2026-02-01')) v(n, s, d)"
        )
        p = profile(s, "t")
    assert p["rows"] == 4
    n, text, day = p["columns"]["n"], p["columns"]["s"], p["columns"]["d"]
    assert (n["nb_missing_values"], n["nb_distinct"]) == (1, 3)
    assert (n["min"], n["max"], n["mean"]) == (1, 3, 2.0)
    assert n["std"] == 1.0  # sample stddev of 1, 2, 3
    assert text["tops"] == [{"value": "a", "count": 3}, {"value": "b", "count": 1}]
    assert "mean" not in text
    assert (day["min"], day["max"], day["nb_missing_values"]) == (
        "2026-01-01",
        "2026-03-01",
        1,
    )


def test_parquet_and_preview(tmp_path):
    import pyarrow.parquet as pq

    run = tmp_path / "run"
    with session(run) as s:
        s.execute("CREATE TABLE t AS SELECT range AS i FROM range(25)")
        size = write_parquet(s, "t", run / "data.parquet")
        assert size > 0
        assert preview_rows(s, "t", 3, 10) == [{"i": 10}, {"i": 11}, {"i": 12}]
    meta = pq.read_metadata(run / "data.parquet")
    assert meta.num_rows == 25
    assert meta.row_group(0).column(0).compression == "ZSTD"


@pytest.mark.slow
@pytest.mark.skipif(not os.environ.get("CI"), reason="1 GB of CSV: CI only")
def test_a_large_csv_stays_within_its_memory_limit(tmp_path):
    """About 1 GB of CSV under a 256 MB limit: done, or a clean EngineError."""
    run = tmp_path / "run"
    raw = run / "raw"
    raw.mkdir(parents=True)
    big = raw / "big.csv"
    with session(run) as s:
        s.execute(
            f"COPY (SELECT range AS id, md5(range::VARCHAR) AS a, "
            f"md5((range * 7)::VARCHAR) AS b, range % 97 AS c FROM range(12000000)) "
            f"TO '{big}' (HEADER, DELIMITER ',')"
        )
    result = FetchResult(
        [big],
        "csv",
        {"encoding": "utf-8", "delimiter": ","},
        Provenance("upload", datetime.now(timezone.utc), "x", big.stat().st_size),
    )
    with session(run, memory_limit="256MB", timeout_s=600) as s:
        try:
            loaded = load(s, result)
        except EngineError as exc:
            assert "memory" in str(exc) or "longer" in str(exc)
        else:
            assert loaded.rows == 12_000_000
