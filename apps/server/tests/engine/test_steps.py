"""Recipe steps compiled to SQL (engine/steps.py): one expected table per op,
and injection attempts that stay inert."""

import pytest

from server.engine.session import EngineError, session
from server.engine.steps import StepError, apply_steps, parse_steps


@pytest.fixture
def s(tmp_path):
    with session(tmp_path / "run") as conn:
        conn.execute(
            "CREATE TABLE source AS SELECT * FROM (VALUES "
            "(1, 'Argol', '1 284,5', '02/01/2026', 'a@x.fr'), "
            "(2, ' Arzano ', '987', '03/02/2026', NULL), "
            "(3, 'Argol', '1 284,5', '02/01/2026', 'a@x.fr'), "
            "(4, 'Bannalec', 'n/a', 'never', 'b@y.fr')"
            ") v(id, name, pop, day, email)"
        )
        yield conn


def rows(s, sql="SELECT * FROM result"):
    return s.fetchall(sql)


def run(s, steps):
    return apply_steps(s, steps)


def test_select_keeps_the_columns_in_order(s):
    out = run(s, [{"op": "select", "columns": ["name", "id"]}])
    assert [n for n, _ in out.schema] == ["name", "id"]
    assert rows(s)[0] == ("Argol", 1)


def test_rename(s):
    out = run(s, [{"op": "rename", "mapping": {"name": "commune"}}])
    assert [n for n, _ in out.schema] == ["id", "commune", "pop", "day", "email"]


def test_cast_with_a_decimal_comma(s):
    out = run(
        s,
        [{"op": "cast", "column": "pop", "to": "double", "decimal_comma": True}],
    )
    assert dict(out.schema)["pop"] == "DOUBLE"
    assert [r[0] for r in rows(s, "SELECT pop FROM result")] == [
        1284.5,
        987.0,
        1284.5,
        None,
    ]


def test_cast_a_date_with_a_format(s):
    run(s, [{"op": "cast", "column": "day", "to": "date", "format": "%d/%m/%Y"}])
    days = [str(r[0]) for r in rows(s, "SELECT day FROM result")]
    assert days == ["2026-01-02", "2026-02-03", "2026-01-02", "None"]


def test_a_failing_cast_can_stop_the_run(s):
    with pytest.raises(EngineError):
        run(s, [{"op": "cast", "column": "pop", "to": "integer", "on_error": "fail"}])


@pytest.mark.parametrize(
    "operator,value,ids",
    [
        ("eq", "Argol", [1, 3]),
        ("ne", "Argol", [2, 4]),
        ("in", ["Argol", "Bannalec"], [1, 3, 4]),
        ("not_in", ["Argol"], [2, 4]),
        ("contains", "rz", [2]),
        ("is_null", None, []),
    ],
)
def test_filter_on_text(s, operator, value, ids):
    run(s, [{"op": "filter", "column": "name", "operator": operator, "value": value}])
    assert [r[0] for r in rows(s, "SELECT id FROM result")] == ids


@pytest.mark.parametrize(
    "operator,value,ids",
    [("lt", 2, [1]), ("le", 2, [1, 2]), ("gt", 3, [4]), ("ge", 3, [3, 4])],
)
def test_filter_on_numbers(s, operator, value, ids):
    run(s, [{"op": "filter", "column": "id", "operator": operator, "value": value}])
    assert [r[0] for r in rows(s, "SELECT id FROM result")] == ids


def test_filter_not_null(s):
    run(s, [{"op": "filter", "column": "email", "operator": "not_null"}])
    assert [r[0] for r in rows(s, "SELECT id FROM result")] == [1, 3, 4]


@pytest.mark.parametrize("keep,ids", [("first", [1, 2, 4]), ("last", [2, 3, 4])])
def test_dedup_on_some_columns(s, keep, ids):
    run(s, [{"op": "dedup", "columns": ["name", "pop"], "keep": keep}])
    assert [r[0] for r in rows(s, "SELECT id FROM result")] == ids


def test_dedup_on_every_column(s):
    out = run(s, [{"op": "select", "columns": ["name", "pop"]}, {"op": "dedup"}])
    assert out.rows == 3


@pytest.mark.parametrize(
    "method,expected",
    [
        ("redact", ["***", None, "***", "***"]),
        ("truncate", ["a", None, "a", "b"]),
    ],
)
def test_mask(s, method, expected):
    run(s, [{"op": "mask", "column": "email", "method": method}])
    assert [r[0] for r in rows(s, "SELECT email FROM result")] == expected


def test_mask_hash_and_drop(s):
    out = run(
        s,
        [
            {"op": "mask", "column": "email", "method": "hash"},
            {"op": "mask", "column": "day", "method": "drop"},
        ],
    )
    hashed = rows(s, "SELECT email FROM result")
    assert len(hashed[0][0]) == 64 and hashed[0] == hashed[2] and hashed[1] == (None,)
    assert "day" not in dict(out.schema)


def test_trim(s):
    run(s, [{"op": "trim", "columns": ["name"]}])
    assert rows(s, "SELECT name FROM result WHERE id = 2") == [("Arzano",)]


def test_limit_keeps_the_files_order(s):
    out = run(s, [{"op": "limit", "rows": 2}])
    assert out.rows == 2 and [r[0] for r in rows(s, "SELECT id FROM result")] == [1, 2]


def test_step_counts(s):
    out = run(
        s,
        [
            {"op": "filter", "column": "email", "operator": "not_null"},
            {"op": "dedup", "columns": ["email"]},
        ],
    )
    assert out.step_rows == [3, 2] and out.rows == 2


class TestValidation:
    def test_an_unknown_column_names_the_step(self, s):
        with pytest.raises(StepError) as exc:
            run(s, [{"op": "trim"}, {"op": "select", "columns": ["nope"]}])
        assert exc.value.index == 1 and "unknown column 'nope'" in str(exc.value)

    def test_a_renamed_column_is_gone_for_the_next_steps(self, s):
        with pytest.raises(StepError, match="Step 2"):
            run(
                s,
                [
                    {"op": "rename", "mapping": {"name": "commune"}},
                    {"op": "trim", "columns": ["name"]},
                ],
            )

    @pytest.mark.parametrize(
        "steps",
        [
            [{"op": "explode"}],
            [{"op": "select", "columns": []}],
            [{"op": "cast", "column": "id", "to": "blob"}],
            [{"op": "limit", "rows": -1}],
            [{"op": "select", "columns": ["id"], "sql": "DROP TABLE x"}],
        ],
    )
    def test_malformed_steps_are_refused(self, steps):
        with pytest.raises(StepError):
            parse_steps(steps)

    def test_two_columns_with_one_name(self, s):
        with pytest.raises(StepError, match="same name"):
            run(s, [{"op": "rename", "mapping": {"name": "id"}}])


class TestInjection:
    """Quotes, semicolons and comments in names and values stay data."""

    EVIL = 'x"; DROP TABLE source; --'

    def test_in_a_column_name(self, s):
        s.execute(
            f'ALTER TABLE source ADD COLUMN "{self.EVIL.replace(chr(34), chr(34) * 2)}" VARCHAR'
        )
        run(
            s,
            [
                {"op": "rename", "mapping": {self.EVIL: "renamed"}},
                {"op": "select", "columns": ["id", "renamed"]},
            ],
        )
        assert s.fetchone("SELECT count(*) FROM source") == (4,)

    @pytest.mark.parametrize(
        "value", ["Argol' OR '1'='1", "Argol'; DROP TABLE source; --", "/* */ 1=1"]
    )
    def test_in_a_value(self, s, value):
        out = run(
            s, [{"op": "filter", "column": "name", "operator": "eq", "value": value}]
        )
        assert out.rows == 0
        assert s.fetchone("SELECT count(*) FROM source") == (4,)

    def test_in_a_new_name(self, s):
        run(s, [{"op": "rename", "mapping": {"name": self.EVIL}}])
        assert s.fetchone("SELECT count(*) FROM source") == (4,)
        assert self.EVIL in [
            r[0] for r in s.fetchall("SELECT column_name FROM (DESCRIBE result)")
        ]

    def test_in_a_cast_format(self, s):
        run(
            s,
            [
                {
                    "op": "cast",
                    "column": "day",
                    "to": "date",
                    "format": "%d'); DROP TABLE source; --",
                }
            ],
        )
        assert s.fetchone("SELECT count(*) FROM source") == (4,)
