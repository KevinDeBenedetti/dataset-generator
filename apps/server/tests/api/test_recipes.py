"""Dataset recipes through the API: CRUD, validation, names, quota, export.

Isolation between users is walked by tests/api/test_tenant_isolation.py.
"""

import io
import json
import zipfile

import pytest

from server.core.config import config
from server.services.users import create_user

RECIPE = {
    "name": "Portfolio Q&A",
    "target_repo": "kevin/github-qa",
    "include_profile": True,
    "sources": [
        {"repo": "alpha", "readme": True, "docs": ["docs/guide.md", "docs/guide.md"]},
        {"repo": "beta", "readme": False, "docs": None},
    ],
    "model_ref": None,
}


@pytest.fixture
def alice(test_db):
    return create_user(test_db, email="alice@test.local", password="pw12345")


@pytest.fixture
def client(alice, client_for):
    return client_for(alice)


def test_create_read_update_delete(client):
    created = client.post("/recipes", json=RECIPE)
    assert created.status_code == 201, created.text
    recipe = created.json()
    assert recipe["name"] == "Portfolio Q&A"
    # A docs file listed twice is kept once.
    assert recipe["sources"][0]["docs"] == ["docs/guide.md"]
    assert recipe["sources"][1] == {"repo": "beta", "readme": False, "docs": None}

    assert client.get(f"/recipes/{recipe['id']}").json()["id"] == recipe["id"]
    assert [r["id"] for r in client.get("/recipes").json()["recipes"]] == [recipe["id"]]

    changed = client.put(
        f"/recipes/{recipe['id']}",
        json={**RECIPE, "include_profile": False, "sources": []},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["include_profile"] is False
    assert changed.json()["sources"] == []

    assert client.delete(f"/recipes/{recipe['id']}").status_code == 204
    assert client.get(f"/recipes/{recipe['id']}").status_code == 404
    assert client.get("/recipes").json() == {"recipes": []}


def test_names_are_unique_per_user(client, client_for, test_db):
    assert client.post("/recipes", json=RECIPE).status_code == 201
    assert client.post("/recipes", json=RECIPE).status_code == 409
    # A renaming onto an existing name is refused too.
    other = client.post("/recipes", json={**RECIPE, "name": "Other"}).json()
    assert client.put(f"/recipes/{other['id']}", json=RECIPE).status_code == 409

    bob = create_user(test_db, email="bob@test.local", password="pw12345")
    assert client_for(bob).post("/recipes", json=RECIPE).status_code == 201


@pytest.mark.parametrize(
    "change",
    [
        {"name": "   "},
        {"target_repo": "not a repo"},
        {"target_repo": "a/b/c"},
        {"sources": [{"repo": "../etc"}]},
        {"sources": [{"repo": "alpha", "docs": ["README.md"]}]},
        {"sources": [{"repo": "alpha", "docs": ["docs/../secret.md"]}]},
        {"sources": [{"repo": "alpha"}, {"repo": "ALPHA"}]},
        {"sources": [{"repo": "alpha", "docs": [f"docs/{i}.md" for i in range(21)]}]},
    ],
)
def test_invalid_recipes_are_refused(client, change):
    assert client.post("/recipes", json={**RECIPE, **change}).status_code == 422


def test_a_bare_repo_name_is_accepted(client):
    response = client.post("/recipes", json={**RECIPE, "target_repo": "github-qa"})
    assert response.status_code == 201


def test_the_quota_holds(client, monkeypatch):
    monkeypatch.setattr(config, "quota_recipes", 1)
    assert client.post("/recipes", json=RECIPE).status_code == 201
    response = client.post("/recipes", json={**RECIPE, "name": "Second"})
    assert response.status_code == 429
    assert "limit 1" in response.json()["detail"]


def test_the_export_holds_the_recipes(client):
    client.post("/recipes", json=RECIPE)

    response = client.get("/me/export")

    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        exported = json.loads(archive.read("recipes.json"))
    assert [r["name"] for r in exported] == ["Portfolio Q&A"]
    assert exported[0]["target_repo"] == "kevin/github-qa"


# --- running a recipe -------------------------------------------------------------


def _queued(run_id="run-1"):
    return {
        "id": run_id,
        "job": "github-recipe",
        "status": "queued",
        "options": {},
        "started_at": "2026-11-04T00:00:00Z",
    }


def test_running_a_recipe_queues_it_as_it_is_now(client, monkeypatch):
    from unittest.mock import AsyncMock

    recipe = client.post(
        "/recipes", json={**RECIPE, "model_ref": "openai:gpt-x"}
    ).json()
    start = AsyncMock(return_value=_queued())
    monkeypatch.setattr("server.api.recipes.start_run", start)

    response = client.post(f"/recipes/{recipe['id']}/run", json={"full_refresh": True})

    assert response.status_code == 202, response.text
    assert response.json()["id"] == "run-1"
    _, _, job_id, options, model_ref = start.call_args.args
    assert job_id == "github-recipe"
    assert options["recipe_id"] == recipe["id"]
    assert options["recipe"]["sources"] == recipe["sources"]
    assert options["full_refresh"] is True
    # The recipe's own model, unless the request names another.
    assert model_ref == "openai:gpt-x"
    client.post(f"/recipes/{recipe['id']}/run", json={"model_ref": "claude:m"})
    assert start.call_args.args[4] == "claude:m"


def test_running_an_unknown_recipe_is_not_found(client):
    assert client.post("/recipes/nope/run", json={}).status_code == 404


def test_a_recipe_shows_its_latest_run(client, alice, test_db):
    from server.models.job_run import JobRun

    recipe = client.post("/recipes", json=RECIPE).json()
    assert recipe["latest_run"] is None
    test_db.add(
        JobRun(
            id="run-9",
            owner_id=alice.id,
            job_id="github-recipe",
            status="succeeded",
            options={"recipe_id": recipe["id"]},
        )
    )
    test_db.commit()

    assert client.get(f"/recipes/{recipe['id']}").json()["latest_run"] == {
        "id": "run-9",
        "status": "succeeded",
    }
    listed = client.get("/recipes").json()["recipes"][0]
    assert listed["latest_run"]["id"] == "run-9"


def test_the_recipe_job_stays_off_the_jobs_page(client):
    jobs = [j["id"] for j in client.get("/jobs").json()["jobs"]]
    assert "github-recipe" not in jobs and "github-personal" in jobs
    assert client.post("/jobs/github-recipe/run", json={}).status_code == 404
