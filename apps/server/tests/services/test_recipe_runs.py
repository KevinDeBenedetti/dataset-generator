"""Running and previewing a recipe (services/recipe_runs.py, the recipe job)."""

import asyncio
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from server.models.job_run import JobRun
from server.services.draft_store import get_store
from server.services.users import create_user

DATA = Path(__file__).resolve().parent.parent / "fixtures" / "data"
STEPS = [
    {"op": "select", "columns": ["code", "libelle", "population_annuelle_2019"]},
    {
        "op": "filter",
        "column": "population_annuelle_2019",
        "operator": "ge",
        "value": 2000,
    },
]


@pytest.fixture
def alice(test_db):
    return create_user(test_db, email="alice@test.local", password="pw12345")


@pytest.fixture
def api(alice, client_for):
    return client_for(alice, real_credentials=True)


@pytest.fixture
def recipe(api):
    data = (DATA / "communes-finistere-cp1252.csv").read_bytes()
    source = api.post(
        "/data-sources/upload",
        files={"file": ("communes.csv", data)},
        data={"name": "Finistère", "licence": "Licence Ouverte 2.0"},
    ).json()
    resp = api.post(
        "/recipes",
        json={
            "name": "Big communes",
            "data_source_id": source["id"],
            "target_repo": "alice/communes",
            "steps": STEPS,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_a_preview_shows_the_first_rows_and_the_step_counts(api, recipe):
    resp = api.post(f"/recipes/{recipe['id']}/preview", json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source_rows"] == 20
    assert body["step_rows"][0] == 20 and body["step_rows"][1] == body["rows"]
    assert [c["name"] for c in body["schema"]] == [
        "code",
        "libelle",
        "population_annuelle_2019",
    ]
    assert all(r["population_annuelle_2019"] >= 2000 for r in body["sample"])
    assert body["error"] is None
    assert [c["name"] for c in body["source_schema"]][:2] == ["code", "libelle"]
    assert [len(schema) for schema in body["step_schemas"]] == [3, 3]


def test_a_preview_tries_unsaved_steps_and_names_the_bad_one(api, recipe):
    steps = [{"op": "trim"}, {"op": "select", "columns": ["nope"]}]
    body = api.post(f"/recipes/{recipe['id']}/preview", json={"steps": steps}).json()
    assert body["error"] == {"step": 1, "message": "unknown column 'nope'"}
    assert body["rows"] == 20  # the steps before it applied


def test_a_preview_reuses_the_loaded_table(api, recipe, alice):
    api.post(f"/recipes/{recipe['id']}/preview", json={})
    cache = get_store().path(alice.id, f"preview-{recipe['id']}", "source.parquet")
    assert cache.is_file()
    stamp = cache.stat().st_mtime_ns
    api.post(f"/recipes/{recipe['id']}/preview", json={"steps": []})
    assert cache.stat().st_mtime_ns == stamp


def test_previews_are_rate_limited(api, recipe, monkeypatch):
    from server.api import data_sources
    from server.services.rate_limit import SlidingWindowRateLimiter

    monkeypatch.setattr(
        data_sources, "_preview_limiter", SlidingWindowRateLimiter(2, 60)
    )
    for _ in range(2):
        assert api.post(f"/recipes/{recipe['id']}/preview", json={}).status_code == 200
    assert api.post(f"/recipes/{recipe['id']}/preview", json={}).status_code == 429


def test_run_queues_a_recipe_job(api, recipe, test_db, datasets_db, monkeypatch):
    monkeypatch.setattr("server.services.jobs.get_scoped_db", datasets_db)
    resp = api.post(f"/recipes/{recipe['id']}/run")
    assert resp.status_code == 202, resp.text
    run = test_db.get(JobRun, resp.json()["id"])
    assert run.job_id == "recipe" and run.options["recipe_id"] == recipe["id"]


def test_a_run_writes_the_parquet_and_the_draft(
    api, recipe, alice, test_db, monkeypatch
):
    from server.services import queue
    from server.services.credentials import resolve_credentials
    from server.jobs.registry import JOBS, TabularRecipeOptions

    run_id = "run-recipe-1"
    token = queue._current_run.set(run_id)
    try:

        async def go():
            return await JOBS["recipe"].runner(
                resolve_credentials(alice.id),
                TabularRecipeOptions(recipe_id=recipe["id"]),
                None,
                lambda *a: None,
            )

        outcome = asyncio.run(go())
    finally:
        queue._current_run.reset(token)
    draft = outcome.draft
    assert draft["kind"] == "table" and draft["source_rows"] == 20
    assert draft["step_rows"][1] == draft["rows"]
    assert draft["provenance"]["licence"] == "Licence Ouverte 2.0"
    report = draft["quality_report"]
    assert report["structure"]["rows"] == draft["rows"] and report["blocking"] == []
    assert draft["profile"]["columns"]["code"]["type"] == "BIGINT"
    parquet = get_store().path(alice.id, run_id, "data.parquet")
    assert pq.read_metadata(parquet).num_rows == draft["rows"]
    from server.models.data_source import DataSource

    source = test_db.get(DataSource, recipe["data_source_id"])
    test_db.refresh(source)
    assert source.last_fingerprint == draft["fingerprint"]
