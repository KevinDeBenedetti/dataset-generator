"""Reviewing a tabular draft: /runs/{run_id}/draft, /draft/rows, /review."""

import asyncio

import pytest

from server.models.data_source import Review
from server.models.identity import AuditLog
from server.models.job_run import JobRun
from server.services.users import create_user

CSV = "id;commune;email\n" + "".join(
    f"{i};Commune {i};user{i}@example.fr\n" for i in range(1, 1201)
)


@pytest.fixture
def alice(test_db):
    return create_user(test_db, email="alice@test.local", password="pw12345")


@pytest.fixture
def hub():
    from server.tests.fake_hub import InMemoryHub

    return InMemoryHub(account="alice")


@pytest.fixture
def api(alice, client_for, hub, datasets_db):
    from server.api.runs import hub_backend
    from server.services import user_secrets

    user_secrets.set_secret(alice.id, "hf_token", "hf_" + "t" * 34)
    client = client_for(alice, real_credentials=True)
    client.app.dependency_overrides[hub_backend] = lambda: hub
    return client


def _draft(
    api,
    alice,
    test_db,
    *,
    visibility="private",
    steps=None,
    run_id="run-1",
    licence=None,
):
    """Upload, make a recipe, run it into a succeeded run."""
    from server.jobs.registry import JOBS, TabularRecipeOptions
    from server.services import queue
    from server.services.credentials import resolve_credentials

    source = api.post(
        "/data-sources/upload",
        files={"file": ("c.csv", CSV.encode())},
        data={
            "name": f"Communes {run_id}",
            **({"licence": licence} if licence else {}),
        },
    ).json()
    recipe = api.post(
        "/recipes",
        json={
            "name": f"Recipe {run_id}",
            "data_source_id": source["id"],
            "target_repo": "alice/communes",
            "visibility": visibility,
            "steps": steps or [],
        },
    ).json()

    async def go():
        return await JOBS["recipe"].runner(
            resolve_credentials(alice.id),
            TabularRecipeOptions(recipe_id=recipe["id"]),
            None,
            lambda *a: None,
        )

    token = queue._current_run.set(run_id)
    try:
        outcome = asyncio.run(go())
    finally:
        queue._current_run.reset(token)
    test_db.add(
        JobRun(
            id=run_id,
            job_id="recipe",
            owner_id=alice.id,
            status="succeeded",
            options={"recipe_id": recipe["id"]},
            draft=outcome.draft,
        )
    )
    test_db.commit()
    return recipe


def test_the_draft_reads_whole(api, alice, test_db):
    _draft(api, alice, test_db)
    body = api.get("/runs/run-1/draft").json()
    assert body["rows"] == 1200
    assert [c["name"] for c in body["schema"]] == ["id", "commune", "email"]
    assert body["schema"][0]["original"] == "id"
    assert body["quality_report"]["pii"][0]["column"] == "email"
    assert body["blocking"] == [] and body["changes"] is None


def test_rows_page_sort_and_filter(api, alice, test_db):
    _draft(api, alice, test_db)
    page = api.get(
        "/runs/run-1/draft/rows", params={"offset": 1000, "limit": 500}
    ).json()
    assert page["total"] == 1200 and len(page["rows"]) == 200
    top = api.get(
        "/runs/run-1/draft/rows", params={"sort": "id", "desc": True, "limit": 1}
    ).json()
    assert top["rows"][0]["id"] == 1200
    found = api.get(
        "/runs/run-1/draft/rows",
        params={"filter_column": "commune", "filter_value": "COMMUNE 119"},
    ).json()
    assert found["total"] == 11  # 119, 1190–1199
    assert api.get("/runs/run-1/draft/rows", params={"limit": 501}).status_code == 422
    assert api.get("/runs/run-1/draft/rows", params={"sort": "nope"}).status_code == 422


def test_an_injection_in_a_filter_stays_data(api, alice, test_db):
    _draft(api, alice, test_db)
    resp = api.get(
        "/runs/run-1/draft/rows",
        params={"filter_column": "commune", "filter_value": "x') OR 1=1; --"},
    )
    assert resp.status_code == 200 and resp.json()["total"] == 0


def test_approve_is_refused_while_a_rule_blocks(api, alice, test_db):
    _draft(api, alice, test_db, visibility="public")
    body = api.get("/runs/run-1/draft").json()
    assert [r["rule"] for r in body["blocking"]] == ["unmasked_pii"]
    resp = api.post("/runs/run-1/review", json={"decision": "approved"})
    assert resp.status_code == 409
    assert resp.json()["detail"]["rules"][0]["column"] == "email"
    assert test_db.query(Review).count() == 0


def test_a_masked_public_draft_is_approved_and_published(api, alice, test_db, hub):
    steps = [{"op": "mask", "column": "email", "method": "hash"}]
    _draft(
        api,
        alice,
        test_db,
        visibility="public",
        steps=steps,
        licence="Licence Ouverte 2.0",
    )
    assert api.get("/runs/run-1/draft").json()["public_refusal"] is None
    resp = api.post(
        "/runs/run-1/review", json={"decision": "approved", "comment": "ok"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["decision"] == "approved" and body["status"] == "published"
    assert body["published_url"] == "https://huggingface.co/datasets/alice/communes"
    assert hub.is_private("alice/communes") is False
    assert "data/train-00000-of-00001.parquet" in hub.files("alice/communes")
    entry = test_db.query(AuditLog).filter_by(action="recipe.review.approved").one()
    assert entry.detail["run_id"] == "run-1" and entry.detail["commit"]


def test_a_public_draft_without_a_licence_is_refused(api, alice, test_db, hub):
    steps = [{"op": "mask", "column": "email", "method": "hash"}]
    _draft(api, alice, test_db, visibility="public", steps=steps)
    assert "licence" in api.get("/runs/run-1/draft").json()["public_refusal"]
    resp = api.post("/runs/run-1/review", json={"decision": "approved"})
    assert resp.status_code == 409 and "licence" in resp.json()["detail"]
    assert not hub.exists("alice/communes")
    assert test_db.query(Review).count() == 0


def test_reject_keeps_the_recipe_and_marks_the_run(api, alice, test_db):
    recipe = _draft(api, alice, test_db)
    resp = api.post(
        "/runs/run-1/review", json={"decision": "rejected", "comment": "bad cast"}
    )
    assert resp.status_code == 200 and resp.json()["status"] == "rejected"
    body = api.get("/runs/run-1/draft").json()
    assert body["status"] == "rejected" and body["review"]["comment"] == "bad cast"
    assert api.get(f"/recipes/{recipe['id']}").status_code == 200
    assert (
        api.post("/runs/run-1/review", json={"decision": "approved"}).status_code == 409
    )
    assert (
        test_db.query(AuditLog).filter_by(action="recipe.review.rejected").count() == 1
    )


def test_changes_against_the_published_version(api, alice, test_db):
    recipe = _draft(api, alice, test_db, run_id="run-0")
    run0 = test_db.get(JobRun, "run-0")
    run0.status = "published"
    test_db.commit()
    from server.jobs.registry import JOBS, TabularRecipeOptions
    from server.services import queue
    from server.services.credentials import resolve_credentials

    api.patch(
        f"/recipes/{recipe['id']}",
        json={
            "steps": [
                {"op": "mask", "column": "email", "method": "drop"},
                {"op": "limit", "rows": 100},
            ]
        },
    )

    async def go():
        return await JOBS["recipe"].runner(
            resolve_credentials(alice.id),
            TabularRecipeOptions(recipe_id=recipe["id"]),
            None,
            lambda *a: None,
        )

    token = queue._current_run.set("run-2")
    try:
        draft = asyncio.run(go()).draft
    finally:
        queue._current_run.reset(token)
    test_db.add(
        JobRun(
            id="run-2",
            job_id="recipe",
            owner_id=alice.id,
            status="succeeded",
            options={"recipe_id": recipe["id"]},
            draft=draft,
        )
    )
    test_db.commit()
    changes = api.get("/runs/run-2/draft").json()["changes"]
    assert changes["removed"] == ["email"]
    assert (changes["rows_before"], changes["rows_after"]) == (1200, 100)


def test_another_users_draft_is_unknown(api, alice, test_db, client_for):
    _draft(api, alice, test_db)
    bob = create_user(test_db, email="bob@test.local", password="pw12345")
    other = client_for(bob)
    assert other.get("/runs/run-1/draft").status_code == 404
    assert other.get("/runs/run-1/draft/rows").status_code == 404
    assert (
        other.post("/runs/run-1/review", json={"decision": "rejected"}).status_code
        == 404
    )


def test_runs_are_listed_with_what_waits_for_review(api, alice, test_db, client_for):
    _draft(api, alice, test_db)
    [run] = api.get("/runs").json()["runs"]
    assert run["run_id"] == "run-1" and run["to_review"] and run["rows"] == 1200
    assert run["recipe_name"] == "Recipe run-1"
    bob = create_user(test_db, email="bob@test.local", password="pw12345")
    assert client_for(bob).get("/runs").json()["runs"] == []
