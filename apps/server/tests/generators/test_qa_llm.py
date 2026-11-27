"""Q&A from rows with the user's model (generators/qa_llm.py) through
qa_build's incremental build: a fake model, an in-memory Hub."""

import asyncio
import json
import re

import pytest

from server.generators.qa_llm import LlmOptions, own_recipe_pair, sources_of_rows
from server.models.job_run import JobRun
from server.services import user_secrets
from server.services.users import create_user
from server.tests.fake_hub import InMemoryHub

CSV = "code;nom;population\n" + "".join(
    f"29{i:03d};Commune {i};{1000 + i}\n" for i in range(1, 7)
)


class FakeModel:
    """Generates two pairs per call from the rows it is given; grades every
    pair 0.9, or 0.2 when its answer holds ``LOW``."""

    def __init__(self):
        self.generations = 0
        self.gradings = 0

    async def __call__(self, req):
        if "Pairs:\n" in req.user:
            self.gradings += 1
            ids = re.findall(r'"id": "([^"]+)"', req.user)
            answers = re.findall(r'"answer": "([^"]*)"', req.user)
            return json.dumps(
                [
                    {"id": i, "score": 0.2 if "LOW" in a else 0.9, "reason": "checked"}
                    for i, a in zip(ids, answers, strict=False)
                ]
            )
        self.generations += 1
        names = re.findall(r"nom: (Commune \d+)", req.user)
        pops = re.findall(r"population: (\d+)", req.user)
        return json.dumps(
            [
                {
                    "question": f"Combien d'habitants compte {n} ?",
                    "answer": f"{n} compte {p} habitants, selon la table des communes du Finistère.",
                    "confidence": 0.9,
                }
                for n, p in zip(names, pops, strict=True)
            ][:2]
        )


@pytest.fixture
def world(test_db, datasets_db, monkeypatch, client_for):
    from server.jobs import qa_build

    for module in ("jobs", "queue"):
        monkeypatch.setattr(f"server.services.{module}.get_scoped_db", datasets_db)
    alice = create_user(test_db, email="alice@test.local", password="pw12345")
    user_secrets.set_secret(alice.id, "hf_token", "hf_" + "t" * 34)
    hub = InMemoryHub(account="alice")
    monkeypatch.setattr("server.services.hub_repo.backend_for", lambda creds: hub)
    model = FakeModel()
    monkeypatch.setattr(
        qa_build, "model_for", lambda creds, ref, complete: ("openai:fake", "fake")
    )
    monkeypatch.setattr(qa_build, "provider_completion", lambda ref, creds: model)
    monkeypatch.setattr(qa_build, "get_embedder", lambda creds: None)
    return alice, client_for(alice, real_credentials=True), hub, model


def _recipe(api, **options):
    source = api.post(
        "/data-sources/upload",
        files={"file": ("c.csv", CSV.encode())},
        data={"name": "Communes", "licence": "Licence Ouverte 2.0"},
    ).json()
    resp = api.post(
        "/recipes",
        json={
            "name": "Communes LLM",
            "data_source_id": source["id"],
            "target_repo": "alice/communes-llm",
            "output_kind": "qa",
            "output_options": {"generator": "llm", "group_size": 2, **options},
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _run(alice, recipe, run_id):
    from server.jobs.registry import JOBS, TabularRecipeOptions
    from server.services import queue
    from server.services.credentials import resolve_credentials

    async def go():
        return await JOBS["recipe"].runner(
            resolve_credentials(alice.id),
            TabularRecipeOptions(recipe_id=recipe["id"]),
            None,
            lambda *a: None,
        )

    token = queue._current_run.set(run_id)
    try:
        return asyncio.run(go())
    finally:
        queue._current_run.reset(token)


def _store(test_db, alice, recipe, run_id, draft):
    test_db.add(
        JobRun(
            id=run_id,
            job_id="recipe",
            owner_id=alice.id,
            status="succeeded",
            options={"recipe_id": recipe["id"]},
            draft=draft,
        )
    )
    test_db.commit()


def test_rows_are_grouped_into_sources():
    options = LlmOptions(group_size=2)
    rows = [{"nom": f"C{i}", "pop": i} for i in range(5)]
    sources = sources_of_rows(options, rows, "r1")
    assert list(sources) == ["r1::rows-0", "r1::rows-1", "r1::rows-2"]
    assert sources["r1::rows-0"].text == "nom: C0\npop: 0\n\nnom: C1\npop: 1"
    by_key = sources_of_rows(
        LlmOptions(group_by="nom", row_template="{nom} ({pop})"), rows, "r1"
    )
    assert by_key["r1::nom=C3"].text == "C3 (3)"


def test_an_unchanged_table_calls_the_model_zero_times(world, test_db):
    alice, api, hub, model = world
    recipe = _recipe(api)
    first = _run(alice, recipe, "run-1").draft
    assert (
        first["kind"] == "qa_llm" and first["model_calls"] == 3 and first["groups"] == 3
    )
    _store(test_db, alice, recipe, "run-1", first)
    published = api.post("/jobs/runs/run-1/publish", json={})
    assert published.status_code == 200, published.text
    rows = hub.files("alice/communes-llm")["train.jsonl"].decode().splitlines()
    assert len(rows) == 6 and json.loads(rows[0])["source"] == "recipe"
    before = model.generations
    again = _run(alice, recipe, "run-2").draft
    assert again["model_calls"] == 0 and model.generations == before
    assert again["dataset"]["kept"] == 6


def test_a_changed_row_regenerates_only_its_group(world, test_db):
    alice, api, hub, model = world
    recipe = _recipe(api)
    _store(test_db, alice, recipe, "run-1", _run(alice, recipe, "run-1").draft)
    api.post("/jobs/runs/run-1/publish", json={})
    # One row's value moves in the data source's file.
    from server.services.draft_store import get_store

    source = api.get(f"/data-sources/{recipe['data_source_id']}").json()
    stored = get_store().path(
        alice.id, "sources", source["id"], source["config"]["stored_name"]
    )
    stored.write_text(CSV.replace("Commune 3;1003", "Commune 3;9999"))
    draft = _run(alice, recipe, "run-2").draft
    assert draft["model_calls"] == 1  # the group of Commune 3 and 4 only


def test_low_graded_pairs_are_held_for_review(world, test_db, monkeypatch):
    alice, api, hub, model = world
    original = FakeModel.__call__

    async def low(self, req):
        raw = await original(self, req)
        if "Pairs:\n" not in req.user:
            raw = raw.replace("habitants, selon", "habitants LOW, selon")
        return raw

    monkeypatch.setattr(FakeModel, "__call__", low)
    recipe = _recipe(api)
    draft = _run(alice, recipe, "run-1").draft
    review = draft["dataset"]["review"]
    assert len(review) == 6 and review[0]["judge_note"] == "checked"
    assert draft["dataset"]["pairs"] == []


def test_the_cost_guard_refuses_a_big_run(world, monkeypatch):
    from server.core.config import config
    from server.services.recipe_runs import RecipeRunError

    alice, api, hub, model = world
    monkeypatch.setattr(config, "quota_tokens_per_run", 10)
    recipe = _recipe(api)
    with pytest.raises(RecipeRunError, match="tokens"):
        _run(alice, recipe, "run-1")
    assert model.generations == 0


def test_the_preview_estimates_and_names_a_missing_model(world, monkeypatch):
    from server.jobs import qa_build

    alice, api, hub, model = world
    recipe = _recipe(api)
    body = api.post(f"/recipes/{recipe['id']}/preview", json={}).json()
    assert body["llm"]["groups"] == 3 and body["llm"]["estimated_tokens"] > 0
    assert "missing" not in body["llm"]

    def no_model(creds, ref, complete):
        raise qa_build.JobError(
            "Your OpenAI-compatible API key is required to run openai:x"
        )

    monkeypatch.setattr(qa_build, "model_for", no_model)
    body = api.post(f"/recipes/{recipe['id']}/preview", json={}).json()
    assert "API key is required" in body["llm"]["missing"]


def test_own_pairs_are_this_recipes():
    own = own_recipe_pair("r1")
    base = {"question": "q?", "answer": "a", "category": "rows", "source": "recipe"}
    assert own({**base, "sources": ["r1::rows-0"]}) is not None
    assert own({**base, "sources": ["r2::rows-0"]}) is None
    assert own({**base, "source": "github", "sources": ["r1::rows-0"]}) is None
