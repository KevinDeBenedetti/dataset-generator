"""The quality report of tabular drafts (review/tabular_quality.py)."""

import time

import pytest

from server.engine.profile import profile
from server.engine.session import session
from server.review.tabular_quality import (
    _iban_ok,
    _nir_ok,
    blocking_rules,
    masked_columns,
    quality_report,
)

# A valid NIR (key computed: 97 - n % 97) and a valid French IBAN.
NIR = "185057800608491"
IBAN = "FR7630006000011234567890189"


def _report(tmp_path, values_sql, steps=(), rules=None, public=False, previous=None):
    with session(tmp_path / "run") as s:
        s.execute(f"CREATE TABLE result AS {values_sql}")
        p = profile(s, "result")
        return quality_report(
            s, "result", p, list(steps), rules, public=public, previous_rows=previous
        )


def _kinds(report):
    return {(c["column"], c["kind"]) for c in report["pii"]}


def test_the_check_digits():
    assert _nir_ok(NIR) and not _nir_ok("185057800608437")
    assert _nir_ok(
        "2 84 12 2A 123 456 "
        + str(97 - int("28412191234 56".replace(" ", "")) % 97).zfill(2)
    )
    assert _iban_ok(IBAN) and not _iban_ok("FR7630006000011234567890188")


def test_personal_data_is_found(tmp_path):
    report = _report(
        tmp_path,
        "SELECT * FROM (VALUES "
        f"('a@b.fr', '06 12 34 56 78', '{NIR}', '{IBAN}', '192.168.0.1'), "
        f"('c@d.com', '+33 1 23 45 67 89', '{NIR}', '{IBAN}', '2001:db8::1')"
        ") v(contact, tel_portable, numero, compte, ip)",
    )
    assert _kinds(report) >= {
        ("contact", "email"),
        ("tel_portable", "phone"),
        ("numero", "nir"),
        ("compte", "iban"),
        ("ip", "ip"),
    }
    suggested = {c["column"]: c["suggested_step"] for c in report["pii"]}
    assert suggested["contact"] == {"op": "mask", "column": "contact", "method": "hash"}


def test_a_column_name_is_a_hint_on_its_own(tmp_path):
    report = _report(tmp_path, "SELECT 'Martin' AS nom, 'Paris' AS ville")
    assert ("nom", "name") in _kinds(report)
    assert not any(c["column"] == "ville" for c in report["pii"])


def test_no_false_positive_on_a_clean_table(tmp_path):
    report = _report(
        tmp_path,
        "SELECT * FROM (VALUES "
        "('29000', '12345678901234', 'Quimper', '48.0', 'FR'), "
        "('75001', '55210055400013', 'Paris', '48.8', 'FR'), "
        "('2A004', '41324451900028', 'Ajaccio', '41.9', 'FR')"
        ") v(code_postal, siret, commune, latitude, pays)",
    )
    assert report["pii"] == []


def test_masked_columns_follow_renames():
    steps = [
        {"op": "mask", "column": "email", "method": "hash"},
        {"op": "rename", "mapping": {"email": "contact"}},
        {"op": "mask", "column": "nom", "method": "drop"},
    ]
    assert masked_columns(steps) == {"contact"}


def test_structure(tmp_path):
    report = _report(
        tmp_path,
        "SELECT * FROM (VALUES "
        "(1, NULL, 'x', NULL), (1, NULL, 'x', NULL), (2, NULL, 'x', 'a')"
        ") v(n, empty, constant, sparse)",
        previous=2,
    )
    s = report["structure"]
    assert s["empty_columns"] == ["empty"]
    assert s["constant_columns"] == ["constant"]
    assert s["mostly_empty_columns"] == [{"column": "sparse", "share": 0.6667}]
    assert s["duplicated_rows"] == 1
    assert s["rows_change"] == 0.5


class TestRules:
    SQL = "SELECT * FROM (VALUES ('a@b.fr', 1), ('c@d.fr', NULL)) v(email, n)"

    def test_unmasked_email_blocks_a_public_dataset_by_default(self, tmp_path):
        report = _report(tmp_path, self.SQL, public=True)
        assert [r["rule"] for r in blocking_rules(report)] == ["unmasked_pii"]

    def test_and_only_warns_on_a_private_one(self, tmp_path):
        report = _report(tmp_path, self.SQL, public=False)
        assert blocking_rules(report) == []
        assert [r["status"] for r in report["rules"]] == ["warn"]

    def test_a_masked_column_passes(self, tmp_path):
        steps = [{"op": "mask", "column": "email", "method": "hash"}]
        report = _report(
            tmp_path,
            "SELECT sha256(email) AS email, n FROM (" + self.SQL + ")",
            steps=steps,
            public=True,
        )
        assert blocking_rules(report) == []

    def test_configured_rules(self, tmp_path):
        rules = {
            "min_rows": 3,
            "max_null_share": 0.25,
            "required_columns": ["n", "code"],
            "severity": "block",
            "unmasked_pii": "off",
        }
        report = _report(tmp_path, self.SQL, rules=rules)
        failed = {r["rule"]: r for r in report["rules"] if r["status"] != "pass"}
        assert set(failed) == {"min_rows", "max_null_share", "required_columns"}
        assert "code" in failed["required_columns"]["message"]
        assert len(blocking_rules(report)) == 3


@pytest.mark.slow
def test_a_million_rows_in_under_five_seconds(tmp_path):
    with session(tmp_path / "run") as s:
        s.execute(
            "CREATE TABLE result AS SELECT range AS id, 'user' || range || '@x.fr' AS email, "
            "lpad((range % 99999)::VARCHAR, 5, '0') AS code_postal, md5(range::VARCHAR) AS h "
            "FROM range(1000000)"
        )
        p = profile(s, "result")
        start = time.monotonic()
        report = quality_report(s, "result", p, [], None, public=True)
        assert time.monotonic() - start < 5
    assert ("email", "email") in _kinds(report)
