"""Data sources (/data-sources) and recipes (/recipes) of the open-data path."""

import pytest

from server.core.config import config
from server.models.job_run import JobRun
from server.services.draft_store import get_store
from server.services.users import create_user


@pytest.fixture
def alice(test_db):
    return create_user(test_db, email="alice@test.local", password="pw12345")


@pytest.fixture
def api(alice, client_for):
    return client_for(alice)


def _source(api, name="Communes", **extra):
    resp = api.post(
        "/data-sources/upload",
        files={"file": ("c.csv", b"a;b\n1;2\n")},
        data={"name": name, **extra},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _recipe(api, source_id, name="Communes table", **extra):
    body = {"name": name, "data_source_id": source_id, "target_repo": "alice/communes"}
    resp = api.post("/recipes", json={**body, **extra})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_a_data_source_round_trip(api):
    created = _source(api, licence="Licence Ouverte 2.0")
    assert (
        created["connector"] == "upload" and created["licence"] == "Licence Ouverte 2.0"
    )
    listed = api.get("/data-sources").json()["data_sources"]
    assert [s["id"] for s in listed] == [created["id"]]
    patched = api.patch(f"/data-sources/{created['id']}", json={"name": "Renamed"})
    assert patched.status_code == 200 and patched.json()["name"] == "Renamed"
    assert api.delete(f"/data-sources/{created['id']}").status_code == 204
    assert api.get(f"/data-sources/{created['id']}").status_code == 404


def test_names_are_unique_per_owner(api, client_for, test_db):
    _source(api)
    again = api.post(
        "/data-sources/upload",
        files={"file": ("c.csv", b"a\n1\n")},
        data={"name": "Communes"},
    )
    assert again.status_code == 409
    bob = create_user(test_db, email="bob@test.local", password="pw12345")
    _source(client_for(bob))


def test_a_recipe_round_trip(api):
    source = _source(api)
    recipe = _recipe(api, source["id"], steps=[{"op": "select", "columns": ["a"]}])
    assert recipe["output_kind"] == "table" and recipe["visibility"] == "private"
    patched = api.patch(f"/recipes/{recipe['id']}", json={"visibility": "public"})
    assert patched.json()["visibility"] == "public"
    assert [r["id"] for r in api.get("/recipes").json()["recipes"]] == [recipe["id"]]
    assert api.delete(f"/recipes/{recipe['id']}").status_code == 204
    assert api.get("/recipes").json()["recipes"] == []


def test_a_recipe_needs_your_own_data_source(api, client_for, test_db):
    bob = create_user(test_db, email="bob@test.local", password="pw12345")
    bobs = _source(client_for(bob))
    resp = api.post(
        "/recipes",
        json={"name": "x", "data_source_id": bobs["id"], "target_repo": "alice/x"},
    )
    assert resp.status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"name": "x", "connector": "Not A Kind"},
        {"name": " ", "connector": "upload"},
        {"name": "x", "connector": "upload", "config": {"blob": "x" * 70_000}},
        {"name": "x", "connector": "nope"},
    ],
)
def test_invalid_data_sources_are_refused(api, body):
    assert api.post("/data-sources", json=body).status_code == 422


def test_invalid_recipes_are_refused(api):
    source = _source(api)
    for extra in (
        {"output_kind": "video"},
        {"visibility": "secret"},
        {"target_repo": "a/b/c"},
    ):
        body = {
            "name": "x",
            "data_source_id": source["id"],
            "target_repo": "alice/x",
            **extra,
        }
        assert api.post("/recipes", json=body).status_code == 422


def test_the_quota_of_data_sources(api, monkeypatch):
    monkeypatch.setattr(config, "quota_data_sources", 1)
    _source(api)
    resp = api.post(
        "/data-sources/upload",
        files={"file": ("d.csv", b"a\n1\n")},
        data={"name": "Two"},
    )
    assert resp.status_code == 429


def test_deleting_a_recipe_deletes_its_run_files(api, alice, test_db):
    source = _source(api)
    recipe = _recipe(api, source["id"])
    test_db.add(
        JobRun(
            id="run-1",
            job_id="recipe",
            owner_id=alice.id,
            status="succeeded",
            options={"recipe_id": recipe["id"]},
        )
    )
    test_db.commit()
    store = get_store()
    store.write(alice.id, "run-1/data.parquet", b"PAR1")
    assert store.exists(alice.id, f"sources/{source['id']}/c.csv")
    assert api.delete(f"/recipes/{recipe['id']}").status_code == 204
    assert not store.exists(alice.id, "run-1/data.parquet")
    assert api.delete(f"/data-sources/{source['id']}").status_code == 204
    assert not store.exists(alice.id, f"sources/{source['id']}/c.csv")


def test_deleting_the_account_deletes_rows_and_files(api, alice, test_db):
    from server.models.data_source import DataSource
    from server.services.admin import delete_account

    _source(api)
    get_store().write(alice.id, "run-x/data.parquet", b"PAR1")
    delete_account(test_db, alice)
    assert test_db.query(DataSource).count() == 0
    assert get_store().size(alice.id) == 0


def test_the_export_lists_data_sources_and_recipes(api, alice, test_db):
    import io
    import json
    import zipfile

    source = _source(api)
    _recipe(api, source["id"])
    resp = api.get("/me/export")
    archive = zipfile.ZipFile(io.BytesIO(resp.content))
    listed = json.loads(archive.read("data_sources.json"))
    assert [s["name"] for s in listed["data_sources"]] == ["Communes"]
    assert [r["name"] for r in listed["recipes"]] == ["Communes table"]
