"""The sandboxed DuckDB session and loading (engine/session.py, engine/load.py)."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from server.connectors.base import FetchResult, Provenance
from server.connectors.sniff import sniff
from server.engine.build import build
from server.engine.load import load, normalise_names
from server.engine.session import EngineError, EngineSession, session

DATA = Path(__file__).resolve().parent.parent / "fixtures" / "data"


def fetched(run_dir: Path, name: str, **options) -> FetchResult:
    raw = run_dir / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    target = raw / name
    target.write_bytes((DATA / name).read_bytes())
    found = sniff(target, name, options or None)
    return FetchResult(
        files=[target],
        format=found.format,
        options=found.options,
        provenance=Provenance("upload", datetime.now(timezone.utc), "x", 1),
    )


def types(loaded):
    return {c.name: c.type for c in loaded.columns}


class TestSandbox:
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM read_csv('/etc/passwd')",
            "SELECT * FROM read_text('/etc/hosts')",
            "COPY (SELECT 1) TO '/tmp/escaped.csv'",
            "ATTACH '/tmp/other.db' AS other",
            "INSTALL excel",
            "LOAD httpfs",
            "SET enable_external_access = true",
            "SET memory_limit = '64GB'",
            "SET allowed_directories = ['/']",
        ],
    )
    def test_nothing_outside_the_run_folder(self, tmp_path, sql):
        with session(tmp_path / "run") as s:
            with pytest.raises(Exception):  # noqa: B017 — DuckDB's own errors
                s.execute(sql)

    def test_a_sibling_folder_is_outside_too(self, tmp_path):
        (tmp_path / "run-other").mkdir()
        (tmp_path / "run-other" / "x.csv").write_text("a\n1\n")
        with session(tmp_path / "run") as s:
            with pytest.raises(Exception):  # noqa: B017
                s.execute(f"SELECT * FROM read_csv('{tmp_path}/run-other/x.csv')")

    def test_the_run_folder_itself_is_usable(self, tmp_path):
        run = tmp_path / "run"
        with session(run) as s:
            s.execute(f"COPY (SELECT 1 AS a) TO '{run}/x.parquet' (FORMAT parquet)")
            assert s.fetchone(f"SELECT a FROM read_parquet('{run}/x.parquet')") == (1,)

    def test_a_query_past_the_timeout_is_interrupted(self, tmp_path):
        s = EngineSession(tmp_path / "run", timeout_s=0.2)
        try:
            with pytest.raises(EngineError, match="longer than"):
                s.execute("SELECT count(*) FROM range(10000000000) a")
        finally:
            s.close()


class TestLoad:
    def test_utf8_bom_csv_with_semicolons(self, tmp_path):
        run = tmp_path / "run"
        with session(run) as s:
            loaded = load(s, fetched(run, "communes-finistere-utf8bom.csv"))
            assert loaded.rows == 20
            t = types(loaded)
            # Commune codes keep their text form; population is a number.
            assert t["code"] == "BIGINT"  # no leading zeros in Finistère (29xxx)
            assert t["population_annuelle_2019"] == "DOUBLE"
            assert t["categorie_population"] == "VARCHAR"  # "b. 1 000 - 3 500"
            names = s.fetchall("SELECT libelle FROM source ORDER BY code LIMIT 2")
            assert names == [("Argol",), ("Arzano",)]

    def test_windows_1252_reads_the_same(self, tmp_path):
        run = tmp_path / "run"
        with session(run) as s:
            loaded = load(s, fetched(run, "communes-finistere-cp1252.csv"))
            assert loaded.rows == 20
            epci = s.fetchone("SELECT epci FROM source WHERE code = 29001")
            assert epci == ("CC Presqu'île de Crozon-Aulne maritime",)

    def test_leading_zeros_and_thousands_separators_stay_text(self, tmp_path):
        run = tmp_path / "run"
        raw = run / "raw"
        raw.mkdir(parents=True)
        (raw / "c.csv").write_text(
            "code;pop;when\n01001;1 284;2026-01-02\n02002;987;2026-02-03\n",
            encoding="utf-8",
        )
        result = FetchResult(
            [raw / "c.csv"],
            "csv",
            {"encoding": "utf-8", "delimiter": ";"},
            Provenance("upload", datetime.now(timezone.utc), "x", 1),
        )
        with session(run) as s:
            t = types(load(s, result))
            assert t == {"code": "VARCHAR", "pop": "VARCHAR", "when": "DATE"}
            assert s.fetchone("SELECT code FROM source LIMIT 1") == ("01001",)

    @pytest.mark.parametrize(
        "name", ["communes.tsv", "communes.json", "communes.jsonl", "communes.parquet"]
    )
    def test_every_format_loads_its_rows(self, tmp_path, name):
        run = tmp_path / "run"
        with session(run) as s:
            loaded = load(s, fetched(run, name))
            assert loaded.rows == 20
            assert [c.name for c in loaded.columns][:2] == ["code", "libelle"]

    def test_excel_keeps_its_cell_types(self, tmp_path):
        run = tmp_path / "run"
        with session(run) as s:
            loaded = load(s, fetched(run, "communes.xlsx"))
            assert loaded.rows == 5
            assert types(loaded)["population_annuelle_2019"] == "DOUBLE"

    def test_a_json_path_reaches_the_records(self, tmp_path):
        import json

        run = tmp_path / "run"
        raw = run / "raw"
        raw.mkdir(parents=True)
        (raw / "doc.json").write_text(
            json.dumps({"meta": {}, "data": {"records": [{"a": 1}, {"a": 2}]}})
        )
        result = FetchResult(
            [raw / "doc.json"],
            "json",
            {"json_path": "data.records"},
            Provenance("upload", datetime.now(timezone.utc), "x", 1),
        )
        with session(run) as s:
            assert load(s, result).rows == 2

    def test_a_ragged_csv_names_its_line(self, tmp_path):
        run = tmp_path / "run"
        raw = run / "raw"
        raw.mkdir(parents=True)
        (raw / "bad.csv").write_text("a;b;c\n1;2;3\n1;2;3;4;5\n", encoding="utf-8")
        result = FetchResult(
            [raw / "bad.csv"],
            "csv",
            {"encoding": "utf-8", "delimiter": ";"},
            Provenance("upload", datetime.now(timezone.utc), "x", 1),
        )
        with session(run) as s:
            with pytest.raises(EngineError, match="columns expected"):
                load(s, result)

    def test_names_are_trimmed_and_unique(self):
        assert normalise_names([" a ", "a", "", "A"]) == ["a", "a_2", "column_3", "A_3"]

    def test_build_writes_the_parquet_and_the_metadata(self, tmp_path):
        import pyarrow.parquet as pq

        run = tmp_path / "run"
        built = build(run, fetched(run, "communes-finistere-cp1252.csv"))
        assert built.rows == 20 and built.data_path == run / "data.parquet"
        assert pq.read_metadata(built.data_path).num_rows == 20
        meta = built.metadata()
        assert meta["schema"][0]["name"] == "code"
        assert meta["profile"]["rows"] == 20 and "rows_data" not in meta


def test_a_type_the_sample_guessed_is_checked_on_every_row(tmp_path, monkeypatch):
    import server.engine.load as engine_load

    monkeypatch.setattr(engine_load, "_TYPE_SAMPLE", 2)
    run = tmp_path / "run"
    raw = run / "raw"
    raw.mkdir(parents=True)
    (raw / "c.csv").write_text("n;z\n1;10\n2;20\nthree;030\n", encoding="utf-8")
    result = FetchResult(
        [raw / "c.csv"],
        "csv",
        {"encoding": "utf-8", "delimiter": ";"},
        Provenance("upload", datetime.now(timezone.utc), "x", 1),
    )
    with session(run) as s:
        t = types(load(s, result))
    # Numbers in the sample, text (and a leading zero) further down.
    assert t == {"n": "VARCHAR", "z": "VARCHAR"}
