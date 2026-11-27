"""Corpus documents from rows (generators/corpus.py) and a corpus recipe run."""

import asyncio

import pyarrow.parquet as pq
import pytest

from server.generators.corpus import CorpusOptions, chunks, documents
from server.services.draft_store import get_store
from server.services.users import create_user

ROWS = [{"code": "29019", "nom": "Brest", "texte": "Un port. " * 10, "pop": 139926}]


def test_one_row_one_document_with_typed_metadata():
    options = CorpusOptions(
        text_template="{nom} : {texte}",
        title_template="{nom}",
        metadata_columns=["code", "pop"],
        id_column="code",
    )
    [doc] = list(documents(options, ROWS))
    assert doc["id"] == "29019" and doc["title"] == "Brest"
    assert doc["metadata"] == {"code": "29019", "pop": 139926}


def test_long_texts_are_chunked_at_boundaries():
    text = ("Une phrase assez longue pour remplir. " * 30).strip()
    parts = chunks(text, 200)
    assert all(len(p) <= 200 for p in parts) and len(parts) > 1
    assert " ".join(parts).replace("  ", " ") == text
    options = CorpusOptions(text_template="{texte}", chunk_chars=200, id_column="code")
    docs = list(documents(options, [{"code": "a", "texte": text}]))
    assert [d["id"] for d in docs][:2] == ["a-1", "a-2"] and "metadata" not in docs[0]


def test_bad_options_are_refused():
    with pytest.raises(ValueError):
        CorpusOptions(text_template="{texte|exec}")
    with pytest.raises(ValueError):
        CorpusOptions(text_template="x", chunk_chars=10)


def test_a_corpus_recipe_run_writes_documents(test_db, datasets_db, client_for):
    from server.jobs.registry import JOBS, TabularRecipeOptions
    from server.services import queue
    from server.services.credentials import resolve_credentials

    alice = create_user(test_db, email="alice@test.local", password="pw12345")
    api = client_for(alice, real_credentials=True)
    csv = "code;nom;texte;dep\n29019;Brest;Port de Bretagne;29\n56121;Lorient;Port du Morbihan;56\n"
    source = api.post(
        "/data-sources/upload",
        files={"file": ("c.csv", csv.encode())},
        data={"name": "C"},
    ).json()
    recipe = api.post(
        "/recipes",
        json={
            "name": "Corpus",
            "data_source_id": source["id"],
            "target_repo": "alice/corpus",
            "output_kind": "corpus",
            "output_options": {
                "text_template": "{nom} : {texte}",
                "title_template": "{nom}",
                "metadata_columns": ["dep"],
                "id_column": "code",
            },
        },
    ).json()

    async def go():
        return await JOBS["recipe"].runner(
            resolve_credentials(alice.id),
            TabularRecipeOptions(recipe_id=recipe["id"]),
            None,
            lambda *a: None,
        )

    token = queue._current_run.set("run-c")
    try:
        draft = asyncio.run(go()).draft
    finally:
        queue._current_run.reset(token)
    assert draft["kind"] == "corpus" and draft["rows"] == 2
    assert [c["name"] for c in draft["schema"]] == ["id", "title", "text", "metadata"]
    table = pq.read_table(get_store().path(alice.id, "run-c", "data.parquet"))
    assert table.column("text").to_pylist() == [
        "Brest : Port de Bretagne",
        "Lorient : Port du Morbihan",
    ]
    # The review page knows it is a corpus (its "Create a collection" link).
    from server.models.job_run import JobRun

    test_db.add(
        JobRun(
            id="run-c",
            job_id="recipe",
            owner_id=alice.id,
            status="succeeded",
            options={"recipe_id": recipe["id"]},
            draft=draft,
        )
    )
    test_db.commit()
    assert api.get("/runs/run-c/draft").json()["kind"] == "corpus"
