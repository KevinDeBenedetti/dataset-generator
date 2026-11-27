"""Scheduled refreshes of recipes (#314): no run when the data source is
unchanged, one run when it changed, publication only when no rule blocks."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from server.models.data_source import DataSource, Publication, Recipe, Review
from server.models.job_run import JobRun
from server.models.job_schedule import JobSchedule
from server.services import user_secrets
from server.services.schedules import queue_due, upsert_schedule
from server.services.users import create_user
from server.tests.fake_hub import InMemoryHub

CSV = "id;commune\n" + "".join(f"{i};Commune {i}\n" for i in range(1, 21))
EMAILS = "id;email\n" + "".join(f"{i};u{i}@example.fr\n" for i in range(1, 21))


@pytest.fixture
def world(test_db, datasets_db, monkeypatch, client_for):
    for module in ("jobs", "queue", "schedules", "recipe_runs"):
        monkeypatch.setattr(f"server.services.{module}.get_scoped_db", datasets_db)
    alice = create_user(test_db, email="alice@test.local", password="pw12345")
    user_secrets.set_secret(alice.id, "hf_token", "hf_" + "t" * 34)
    hub = InMemoryHub(account="alice")
    monkeypatch.setattr("server.services.hub_repo.backend_for", lambda creds: hub)
    return {"alice": alice, "api": client_for(alice, real_credentials=True), "hub": hub}


def _recipe(world, data=CSV, visibility="private", steps=None):
    api = world["api"]
    source = api.post(
        "/data-sources/upload",
        files={"file": ("c.csv", data.encode())},
        data={
            "name": f"Source {len(data)} {visibility}",
            "licence": "Licence Ouverte 2.0",
        },
    ).json()
    return api.post(
        "/recipes",
        json={
            "name": f"Recipe {len(data)} {visibility}",
            "data_source_id": source["id"],
            "target_repo": "alice/communes",
            "visibility": visibility,
            "steps": steps or [],
        },
    ).json()


def _due(test_db, owner_id, recipe_id, publish=True):
    upsert_schedule(
        test_db,
        owner_id,
        "recipe",
        recipe_id,
        options={"recipe_id": recipe_id},
        every="day",
        publish=publish,
    )
    row = test_db.query(JobSchedule).filter_by(scope=recipe_id).one()
    row.next_run_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    test_db.commit()
    return row


def _execute(run_id):
    from server.services.queue import execute

    return asyncio.run(execute(run_id, "test-worker"))


def _claim(test_db, run_id):
    from server.services.queue import claim_next

    assert claim_next("test-worker") == run_id


def test_a_first_scheduled_run_publishes_what_passes(world, test_db):
    alice, hub = world["alice"], world["hub"]
    recipe = _recipe(world)
    _due(test_db, alice.id, recipe["id"])
    [run_id] = queue_due()
    run = test_db.get(JobRun, run_id)
    assert run.options == {
        "recipe_id": recipe["id"],
        "publish": True,
        "scheduled": True,
    }
    _claim(test_db, run_id)
    assert _execute(run_id) == "published"
    test_db.expire_all()
    run = test_db.get(JobRun, run_id)
    assert run.status == "published" and run.published_url.endswith("alice/communes")
    assert hub.log("alice/communes")[-1].startswith("refresh: ")
    assert test_db.query(Publication).count() == 1
    review = test_db.query(Review).one()
    assert review.decision == "approved" and review.reviewer_id is None


def test_an_unchanged_source_starts_no_run(world, test_db):
    alice = world["alice"]
    recipe = _recipe(world)
    row = _due(test_db, alice.id, recipe["id"])
    [run_id] = queue_due()
    _claim(test_db, run_id)
    _execute(run_id)
    row.next_run_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    test_db.commit()
    assert queue_due() == []
    test_db.refresh(row)
    assert row.skipped["reason"].startswith("unchanged since ")
    assert test_db.query(JobRun).count() == 1


def test_an_edited_recipe_runs_again(world, test_db):
    alice, api = world["alice"], world["api"]
    recipe = _recipe(world)
    row = _due(test_db, alice.id, recipe["id"])
    [first] = queue_due()
    _claim(test_db, first)
    _execute(first)
    api.patch(f"/recipes/{recipe['id']}", json={"steps": [{"op": "limit", "rows": 5}]})
    row.next_run_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    test_db.commit()
    assert len(queue_due()) == 1


def test_a_changed_data_gouv_resource_runs(world, test_db, monkeypatch):
    """The cheap check says changed: one run is queued."""
    from server.connectors.datagouv import DatagouvConnector

    alice = world["alice"]
    recipe = _recipe(world)
    source = test_db.get(DataSource, recipe["data_source_id"])
    source.connector = "datagouv"
    source.config = {
        "dataset_id": "d1",
        "resource_id": "r1",
        "mode": "file",
        "filters": [],
        "max_pages": 500,
    }
    source.last_fingerprint = "sha1:old"
    source.last_fetched_at = datetime.now(timezone.utc)
    test_db.add(
        JobRun(
            id="earlier",
            job_id="recipe",
            owner_id=alice.id,
            status="published",
            options={"recipe_id": recipe["id"]},
            started_at=datetime.now(timezone.utc) + timedelta(seconds=1),
        )
    )
    test_db.commit()
    _due(test_db, alice.id, recipe["id"])

    async def changed(self, owner, sid, config, version):
        return False

    monkeypatch.setattr(DatagouvConnector, "unchanged", changed)
    assert len(queue_due()) == 1

    async def same(self, owner, sid, config, version):
        return True

    row = test_db.query(JobSchedule).one()
    row.next_run_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    test_db.query(JobRun).filter(JobRun.id != "earlier").delete()
    test_db.commit()
    monkeypatch.setattr(DatagouvConnector, "unchanged", same)
    assert queue_due() == []


def test_a_blocking_rule_leaves_a_draft_for_review(world, test_db):
    alice, hub = world["alice"], world["hub"]
    recipe = _recipe(world, data=EMAILS, visibility="public")
    _due(test_db, alice.id, recipe["id"])
    [run_id] = queue_due()
    _claim(test_db, run_id)
    assert _execute(run_id) == "succeeded"
    test_db.expire_all()
    run = test_db.get(JobRun, run_id)
    assert run.status == "succeeded" and run.draft["quality_report"]["blocking"]
    assert not hub.exists("alice/communes")
    listed = world["api"].get("/runs").json()["runs"]
    assert listed[0]["to_review"] is True


def test_a_schedule_that_does_not_publish_stops_at_a_draft(world, test_db):
    alice, hub = world["alice"], world["hub"]
    recipe = _recipe(world)
    _due(test_db, alice.id, recipe["id"], publish=False)
    [run_id] = queue_due()
    _claim(test_db, run_id)
    assert _execute(run_id) == "succeeded"
    assert not hub.exists("alice/communes")


def test_two_recipes_due_together_run_one_at_a_time(world, test_db):
    alice = world["alice"]
    first = _recipe(world)
    second = _recipe(world, data=CSV + "21;Commune 21\n")
    _due(test_db, alice.id, first["id"])
    _due(test_db, alice.id, second["id"])
    queued = queue_due()
    assert len(queued) == 1
    waiting = [r for r in test_db.query(JobSchedule) if r.last_run_id is None]
    assert len(waiting) == 1 and waiting[0].skipped is None


def test_the_schedule_routes(world, test_db):
    api = world["api"]
    recipe = _recipe(world)
    assert api.get(f"/recipes/{recipe['id']}/schedule").status_code == 404
    saved = api.put(
        f"/recipes/{recipe['id']}/schedule", json={"every": "week", "at_hour": 5}
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["every"] == "week" and body["publish"] is True and body["next_run_at"]
    assert api.get(f"/recipes/{recipe['id']}/schedule").json()["at_hour"] == 5
    assert api.delete(f"/recipes/{recipe['id']}/schedule").status_code == 204
    assert test_db.query(Recipe).count() == 1


def test_a_source_without_a_cheap_check_is_compared_after_the_fetch(
    world, test_db, monkeypatch
):
    """No cheap check (or it says "maybe"): the run fetches, finds the same
    fingerprint, and ends with nothing to review."""
    from server.connectors.upload import UploadConnector

    alice = world["alice"]
    recipe = _recipe(world)
    row = _due(test_db, alice.id, recipe["id"], publish=False)
    [first] = queue_due()
    _claim(test_db, first)
    _execute(first)

    async def maybe(self, owner, sid, config, version):
        return False

    monkeypatch.setattr(UploadConnector, "unchanged", maybe)
    row.next_run_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    test_db.commit()
    [second] = queue_due()
    _claim(test_db, second)
    assert _execute(second) == "succeeded"
    test_db.expire_all()
    run = test_db.get(JobRun, second)
    assert run.draft is None
    assert run.result["metrics"][0][0] == "Unchanged"


def test_new_reading_options_run_again(world, test_db):
    alice, api = world["alice"], world["api"]
    recipe = _recipe(world)
    row = _due(test_db, alice.id, recipe["id"])
    [first] = queue_due()
    _claim(test_db, first)
    _execute(first)
    source = api.get(f"/data-sources/{recipe['data_source_id']}").json()
    config = {
        **source["config"],
        "options": {**source["config"]["options"], "delimiter": ","},
    }
    api.patch(f"/data-sources/{source['id']}", json={"config": config})
    row.next_run_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    test_db.commit()
    assert len(queue_due()) == 1
