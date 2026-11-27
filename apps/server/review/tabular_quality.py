"""The quality report of a tabular draft (ADR 0006).

Computed in the run's DuckDB session after the steps, on the ``result`` table:

- **personal data candidates**, per column: the share of matching values on a
  random sample of at most 10 000 rows (e-mail, French phone number, IBAN,
  NIR with its key, IP address), or a column name that says so (``nom``,
  ``email``, ``telephone``…). Each suggests a ``mask`` step;
- **structure**: empty, constant and mostly-empty columns, duplicated rows,
  the row count against the previous published version;
- **rules** from the user's quality-rule set (``tabular``): minimum rows,
  maximum empty share per column, required columns, unmasked personal data.
  ``block`` stops the approval (409), ``warn`` is shown.
"""

import ipaddress
import re
from typing import Any, Dict, Iterable, List, Optional, Set

from server.engine.session import EngineSession, quote_ident

SAMPLE_ROWS = 10_000
# A column is a candidate when at least this share of its sampled values match.
MIN_SHARE = 0.1
MOSTLY_EMPTY = 0.5

_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_PHONE_FR = re.compile(r"^(?:(?:\+|00)33[\s.-]?|0)[1-9](?:[\s.-]?\d{2}){4}$")
_IBAN = re.compile(r"^[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}\s?[A-Z0-9]{1,4}$")
_NIR = re.compile(
    r"^([12])\s?(\d{2})\s?(0[1-9]|1[0-2]|[2-9]\d)\s?(\d{2}|2[AB])\s?(\d{3})\s?(\d{3})\s?(\d{2})$"
)

# Words in a column name that say it holds personal data.
NAME_HINTS = (
    "nom",
    "prenom",
    "prénom",
    "name",
    "firstname",
    "lastname",
    "email",
    "mail",
    "courriel",
    "telephone",
    "téléphone",
    "tel",
    "phone",
    "mobile",
    "adresse",
    "address",
    "date_naissance",
    "naissance",
    "birth",
    "birthdate",
    "iban",
    "nir",
)
# The kinds whose unmasked presence blocks a public dataset by default.
SENSITIVE = ("email", "phone", "nir")


def _iban_ok(value: str) -> bool:
    compact = value.replace(" ", "").upper()
    rearranged = compact[4:] + compact[:4]
    digits = "".join(str(int(c, 36)) for c in rearranged)
    return int(digits) % 97 == 1


def _nir_ok(value: str) -> bool:
    match = _NIR.match(value.strip().upper())
    if not match:
        return False
    sex, year, month, dept, commune, order, key = match.groups()
    dept_digits = {"2A": "19", "2B": "18"}.get(dept, dept)
    number = int(sex + year + month + dept_digits + commune + order)
    return 97 - number % 97 == int(key)


def _ip(value: str) -> bool:
    if not any(c in value for c in ".:"):
        return False
    try:
        ipaddress.ip_address(value.strip())
        return True
    except ValueError:
        return False


DETECTORS = {
    "email": lambda v: bool(_EMAIL.match(v)),
    "phone": lambda v: bool(_PHONE_FR.match(v)),
    "iban": lambda v: bool(_IBAN.match(v.upper())) and _iban_ok(v),
    "nir": _nir_ok,
    "ip": _ip,
}


def _name_hint(column: str) -> Optional[str]:
    tokens = re.split(r"[^0-9a-zà-ÿ]+", column.lower())
    joined = "_".join(t for t in tokens if t)
    for hint in NAME_HINTS:
        if hint in tokens or (("_" in hint) and hint in joined):
            return hint
    return None


def masked_columns(steps: Iterable[Dict[str, Any]]) -> Set[str]:
    """The output columns a ``mask`` step (hash, redact, truncate) covers,
    followed through later renames."""
    masked: Set[str] = set()
    for step in steps:
        op = step.get("op")
        if op == "mask" and step.get("method") != "drop":
            masked.add(str(step.get("column")))
        elif op == "rename":
            mapping = step.get("mapping") or {}
            masked = {mapping.get(c, c) for c in masked}
    return masked


def pii_candidates(
    session: EngineSession, table: str, masked: Set[str]
) -> List[Dict[str, Any]]:
    t = quote_ident(table)
    described = session.fetchall(f"SELECT column_name, column_type FROM (DESCRIBE {t})")
    columns = [name for name, kind in described if kind.upper().startswith("VARCHAR")]
    hinted = {name: _name_hint(name) for name, _ in described}
    found: List[Dict[str, Any]] = []
    sample: List[tuple] = []
    if columns:
        select = ", ".join(quote_ident(c) for c in columns)
        sample = session.fetchall(
            f"SELECT {select} FROM {t} USING SAMPLE {SAMPLE_ROWS} ROWS"
        )
    for i, column in enumerate(columns):
        values = [str(row[i]).strip() for row in sample if row[i] not in (None, "")]
        if not values:
            continue
        for kind, detect in DETECTORS.items():
            hits = sum(1 for v in values if detect(v))
            share = hits / len(values)
            if hits and share >= MIN_SHARE:
                found.append(
                    _candidate(
                        column, kind, share, len(values), "values", column in masked
                    )
                )
    reported = {c["column"] for c in found}
    for column, hint in hinted.items():
        if hint and column not in reported:
            found.append(
                _candidate(column, "name", None, 0, f"name: {hint}", column in masked)
            )
    return found


def _candidate(
    column: str,
    kind: str,
    share: Optional[float],
    sampled: int,
    reason: str,
    masked: bool,
) -> Dict[str, Any]:
    return {
        "column": column,
        "kind": kind,
        "share": None if share is None else round(share, 4),
        "sampled": sampled,
        "reason": reason,
        "masked": masked,
        "suggested_step": {"op": "mask", "column": column, "method": "hash"},
    }


def structure(
    session: EngineSession,
    table: str,
    profile: Dict[str, Any],
    previous_rows: Optional[int] = None,
) -> Dict[str, Any]:
    rows = int(profile.get("rows") or 0)
    columns = profile.get("columns") or {}
    empty, constant, mostly_empty = [], [], []
    for name, info in columns.items():
        missing = int(info.get("nb_missing_values") or 0)
        if rows and missing == rows:
            empty.append(name)
        elif rows and missing / rows > MOSTLY_EMPTY:
            mostly_empty.append({"column": name, "share": round(missing / rows, 4)})
        if rows > 1 and missing == 0 and int(info.get("nb_distinct") or 0) == 1:
            constant.append(name)
    t = quote_ident(table)
    distinct = session.fetchone(f"SELECT count(*) FROM (SELECT DISTINCT * FROM {t})")
    duplicates = rows - (int(distinct[0]) if distinct else rows)
    change = None
    if previous_rows:
        change = round((rows - previous_rows) / previous_rows, 4)
    return {
        "rows": rows,
        "empty_columns": empty,
        "constant_columns": constant,
        "mostly_empty_columns": mostly_empty,
        "duplicated_rows": duplicates,
        "previous_rows": previous_rows,
        "rows_change": change,
    }


# --- rules --------------------------------------------------------------------

DEFAULT_RULES: Dict[str, Any] = {
    "min_rows": None,
    "max_null_share": None,
    "required_columns": [],
    # "block", "warn" or "off"; "auto": block the sensitive kinds when public.
    "unmasked_pii": "auto",
    # What a failed min_rows / max_null_share / required_columns rule does.
    "severity": "warn",
}


def evaluate_rules(
    rules: Dict[str, Any],
    report: Dict[str, Any],
    profile: Dict[str, Any],
    *,
    public: bool,
) -> List[Dict[str, Any]]:
    rules = {**DEFAULT_RULES, **(rules or {})}
    severity = rules["severity"] if rules["severity"] in ("warn", "block") else "warn"
    out: List[Dict[str, Any]] = []
    rows = report["structure"]["rows"]
    if rules["min_rows"] is not None:
        ok = rows >= int(rules["min_rows"])
        out.append(
            _rule(
                "min_rows",
                ok,
                severity,
                f"{rows} rows, at least {rules['min_rows']} expected",
            )
        )
    if rules["max_null_share"] is not None:
        limit = float(rules["max_null_share"])
        over = [
            name
            for name, info in (profile.get("columns") or {}).items()
            if rows and int(info.get("nb_missing_values") or 0) / rows > limit
        ]
        out.append(
            _rule(
                "max_null_share",
                not over,
                severity,
                f"columns more than {limit:.0%} empty: {', '.join(over)}"
                if over
                else "",
            )
        )
    required = list(rules["required_columns"] or [])
    if required:
        present = set((profile.get("columns") or {}).keys())
        missing = [c for c in required if c not in present]
        out.append(
            _rule(
                "required_columns",
                not missing,
                severity,
                f"missing columns: {', '.join(missing)}" if missing else "",
            )
        )
    mode = rules["unmasked_pii"]
    if mode != "off":
        unmasked = [c for c in report["pii"] if not c["masked"]]
        for candidate in unmasked:
            if mode == "auto":
                level = "block" if public and candidate["kind"] in SENSITIVE else "warn"
            else:
                level = mode if mode in ("warn", "block") else "warn"
            out.append(
                _rule(
                    "unmasked_pii",
                    False,
                    level,
                    f"'{candidate['column']}' may hold personal data ({candidate['reason']})",
                    column=candidate["column"],
                )
            )
    return out


def _rule(
    name: str, ok: bool, severity: str, message: str, **extra: Any
) -> Dict[str, Any]:
    return {
        "rule": name,
        "status": "pass" if ok else severity,
        "message": "" if ok else message,
        **extra,
    }


def quality_report(
    session: EngineSession,
    table: str,
    profile: Dict[str, Any],
    steps: List[Dict[str, Any]],
    rules: Optional[Dict[str, Any]] = None,
    *,
    public: bool = False,
    previous_rows: Optional[int] = None,
) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "pii": pii_candidates(session, table, masked_columns(steps)),
        "structure": structure(session, table, profile, previous_rows),
    }
    report["rules"] = evaluate_rules(rules or {}, report, profile, public=public)
    report["blocking"] = [r for r in report["rules"] if r["status"] == "block"]
    return report


def blocking_rules(report: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The rules that stop an approval (an older draft has none)."""
    return list((report or {}).get("blocking") or [])
