"""The migration graph is one straight line: unique ids, one base, one head.

Runs without a database — it only reads the scripts. A copied revision id (two
files claiming the same ``revision``) otherwise surfaces only at startup, as an
Alembic "cycle detected" error that stops the server from booting.
"""

import ast
from collections import Counter
from pathlib import Path

from alembic.script import ScriptDirectory

from server.migrations.utils.db_utils import get_alembic_config

VERSIONS = Path(__file__).parents[2] / "migrations" / "versions"


def _declared(name: str) -> list:
    values = []
    for path in sorted(VERSIONS.glob("*.py")):
        for node in ast.parse(path.read_text()).body:
            if (
                isinstance(node, ast.AnnAssign)
                and getattr(node.target, "id", "") == name
                and node.value is not None
            ):
                values.append((path.name, ast.literal_eval(node.value)))
    return values


def test_every_revision_id_is_unique():
    counts = Counter(rev for _, rev in _declared("revision"))
    duplicates = {rev: n for rev, n in counts.items() if n > 1}
    assert not duplicates, f"revision ids used more than once: {duplicates}"


def test_each_file_is_named_after_its_revision():
    for filename, rev in _declared("revision"):
        assert filename.startswith(f"{rev}_"), (filename, rev)


def test_the_history_is_linear_with_a_single_head(monkeypatch):
    monkeypatch.chdir(Path(__file__).parents[2])  # script_location is "migrations"
    script = ScriptDirectory.from_config(get_alembic_config("sqlite://"))
    assert len(script.get_heads()) == 1, script.get_heads()
    assert len(script.get_bases()) == 1, script.get_bases()
    # Walking the whole chain also proves there is no cycle.
    assert len(list(script.walk_revisions())) == len(_declared("revision"))
