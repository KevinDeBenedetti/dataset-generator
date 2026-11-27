"""Q&A pairs from rows with templates (generators/facts.py)."""

from datetime import date

import pytest

from server.generators.facts import (
    NBSP,
    FactsOptions,
    FactTemplate,
    TemplateError,
    check_columns,
    facts,
    render,
)

ROWS = [
    {
        "code": "29019",
        "nom": "Brest",
        "population": 139926,
        "maj": date(2026, 1, 2),
        "surface": 49.51,
    },
    {
        "code": "29232",
        "nom": "Quimper",
        "population": 63405,
        "maj": date(2026, 3, 1),
        "surface": 84.45,
    },
]
TEMPLATES = [
    {
        "question": "Quelle est la population de {nom} ?",
        "answer": "{nom} compte {population|number} habitants (au {maj|date_fr}).",
    },
    {
        "question": "Quelle est la superficie de {nom} ?",
        "answer": "{surface|decimal} km²",
        "category": "superficie",
    },
]


def options(**extra):
    return FactsOptions.model_validate({"templates": TEMPLATES, **extra})


def test_two_templates_give_two_pairs_per_row_in_french():
    pairs = facts(options(), ROWS, source="https://x", recipe_id="r", created_at="t")
    assert len(pairs) == 4
    assert (
        pairs[0]["answer"]
        == f"Brest compte 139{NBSP}926 habitants (au 2 janvier 2026)."
    )
    assert pairs[1]["answer"] == "49,51 km²" and pairs[1]["category"] == "superficie"
    assert pairs[2]["answer"].endswith("(au 1er mars 2026).")
    assert {p["confidence"] for p in pairs} == {1.0}


def test_ids_are_stable_and_follow_the_key_column():
    by_content = facts(options(), ROWS, source="s", recipe_id="r", created_at="t")
    again = facts(options(), ROWS, source="s", recipe_id="r", created_at="later")
    assert [p["id"] for p in by_content] == [p["id"] for p in again]
    keyed = facts(
        options(key_column="code"),
        ROWS,
        source="https://x",
        recipe_id="r",
        created_at="t",
    )
    changed = [{**ROWS[0], "population": 140000}, ROWS[1]]
    rekeyed = facts(
        options(key_column="code"),
        changed,
        source="https://x",
        recipe_id="r",
        created_at="t",
    )
    assert (
        keyed[0]["id"] == rekeyed[0]["id"]
        and keyed[0]["answer"] != rekeyed[0]["answer"]
    )
    assert keyed[0]["source_url"] == "https://x#29019"


def test_a_condition_selects_rows():
    templates = [
        {
            **TEMPLATES[0],
            "condition": {"column": "population", "operator": "gt", "value": 100000},
        }
    ]
    pairs = facts(
        FactsOptions(templates=templates), ROWS, source="", recipe_id="r", created_at=""
    )
    assert [p["question"] for p in pairs] == ["Quelle est la population de Brest ?"]


def test_max_pairs_bounds_a_run():
    assert (
        len(facts(options(max_pairs=3), ROWS, source="", recipe_id="r", created_at=""))
        == 3
    )


@pytest.mark.parametrize(
    "text",
    [
        "{{ ''.__class__ }}",
        "{{ ''.__class__.__mro__[1].__subclasses__() }}",
        "{{7*7}}",
    ],
)
def test_template_syntax_never_evaluates(text):
    # Double braces are literal braces: what is between them is printed as is.
    assert render(text, {}) == text.replace("{{", "{").replace("}}", "}").strip()


@pytest.mark.parametrize(
    "text",
    ["{nom|exec}", "{nom", "Population: }", "{__class__}"],
)
def test_bad_templates_are_refused(text):
    with pytest.raises((TemplateError, ValueError)):
        FactTemplate(question=text, answer="x")
        render(text, ROWS[0])


def test_an_unknown_column_is_named():
    bad = FactsOptions(templates=[{"question": "{nom}", "answer": "{habitants}"}])
    with pytest.raises(TemplateError, match="no column 'habitants'"):
        check_columns(bad, ROWS[0].keys())


def test_long_output_is_bounded():
    row = {"t": "x" * 10_000}
    assert len(render("{t}", row)) == 4000


def test_template_length_is_bounded():
    with pytest.raises(ValueError):
        FactTemplate(question="x" * 1001, answer="y")
