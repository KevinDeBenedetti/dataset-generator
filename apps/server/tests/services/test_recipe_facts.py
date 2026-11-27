"""A facts recipe end to end: run → Q&A draft → the existing Q&A publication."""

import asyncio
import json

import pytest

from server.models.job_run import JobRun
from server.services import user_secrets
from server.services.users import create_user
from server.tests.fake_hub import InMemoryHub

CSV = "code;nom;population\n29019;Brest;139926\n29232;Quimper;63405\n29103;Lorient;57000\n"
TEMPLATES = [
    {
        "question": "Quelle est la population de {nom} ?",
        "answer": "{nom} compte {population|number} habitants.",
    },
    {"question": "Quel est le code INSEE de {nom} ?", "answer": "{code}"},
]


@pytest.fixture
def world(test_db, datasets_db, monkeypatch, client_for):
    for module in ("jobs", "queue"):
        monkeypatch.setattr(f"server.services.{module}.get_scoped_db", datasets_db)
    monkeypatch.setattr(
        "server.services.drafts.get_scoped_db", datasets_db, raising=False
    )
    alice = create_user(test_db, email="alice@test.local", password="pw12345")
    user_secrets.set_secret(alice.id, "hf_token", "hf_" + "t" * 34)
    hub = InMemoryHub(account="alice")
    monkeypatch.setattr("server.services.hub_repo.backend_for", lambda creds: hub)
    return alice, client_for(alice, real_credentials=True), hub


def _facts_recipe(api):
    source = api.post(
        "/data-sources/upload",
        files={"file": ("c.csv", CSV.encode())},
        data={"name": "Communes"},
    ).json()
    resp = api.post(
        "/recipes",
        json={
            "name": "Communes Q&A",
            "data_source_id": source["id"],
            "target_repo": "alice/communes-qa",
            "output_kind": "qa",
            "output_options": {
                "generator": "facts",
                "templates": TEMPLATES,
                "key_column": "code",
            },
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _run(alice, recipe, run_id="run-qa"):
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


def test_the_preview_shows_the_pairs(world):
    _, api, _ = world
    recipe = _facts_recipe(api)
    body = api.post(f"/recipes/{recipe['id']}/preview", json={}).json()
    assert len(body["pairs"]) == 6
    assert body["pairs"][0]["answer"] == "Brest compte 139 926 habitants."


def test_a_facts_run_is_published_like_a_q_and_a_draft(world, test_db):
    alice, api, hub = world
    recipe = _facts_recipe(api)
    outcome = _run(alice, recipe)
    draft = outcome.draft
    assert draft["kind"] == "qa" and len(draft["pairs"]) == 6
    assert draft["repo_id"] == "alice/communes-qa"
    test_db.add(
        JobRun(
            id="run-qa",
            job_id="recipe",
            owner_id=alice.id,
            status="succeeded",
            options={"recipe_id": recipe["id"]},
            draft=draft,
        )
    )
    test_db.commit()
    # The existing Q&A review shows it...
    preview = api.get("/jobs/runs/run-qa").json()
    assert preview["status"] == "succeeded"
    # ...and the existing publication merges it, leaving one pair out.
    left_out = draft["pairs"][0]["id"]
    published = api.post("/jobs/runs/run-qa/publish", json={"exclude": [left_out]})
    assert published.status_code == 200, published.text
    rows = [
        json.loads(line)
        for line in hub.files("alice/communes-qa")["data/train.jsonl"]
        .decode()
        .splitlines()
    ]
    assert len(rows) == 5 and {"id", "question", "answer", "source_url"} <= set(rows[0])


def test_a_template_naming_a_missing_column_fails_the_run(world):
    alice, api, _ = world
    recipe = _facts_recipe(api)
    api.patch(
        f"/recipes/{recipe['id']}",
        json={
            "output_options": {
                "generator": "facts",
                "templates": [{"question": "{x}", "answer": "{y}"}],
            }
        },
    )
    from server.services.recipe_runs import RecipeRunError

    with pytest.raises(RecipeRunError, match="no column 'x'"):
        _run(alice, recipe)


def test_the_runs_list_says_which_review(world, test_db):
    alice, api, _ = world
    recipe = _facts_recipe(api)
    draft = _run(alice, recipe).draft
    test_db.add(
        JobRun(
            id="run-qa",
            job_id="recipe",
            owner_id=alice.id,
            status="succeeded",
            options={"recipe_id": recipe["id"]},
            draft=draft,
        )
    )
    test_db.commit()
    assert api.get("/runs").json()["runs"][0]["kind"] == "qa"
