"""Publishing an approved tabular draft (services/tabular_publish.py,
hub/card.py, hub/licences.py, HubDatasetRepo.publish_table)."""

import io
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from huggingface_hub import DatasetCard

from server.hub.card import tabular_card
from server.hub.licences import public_refusal, resolve
from server.models.data_source import Publication
from server.models.job_run import JobRun
from server.services.draft_store import get_store
from server.services.hub_repo import DatasetMoved, RepoNotOurs, RepoNotPrivate
from server.services.tabular_publish import PublishRefused, publish
from server.services.users import create_user
from server.tests.creds import make_creds
from server.tests.fake_hub import InMemoryHub

DRAFT: dict = {
    "kind": "table",
    "recipe_id": "rec-1",
    "target_repo": "alice/communes",
    "visibility": "private",
    "rows": 2,
    "schema": [{"name": "code", "type": "VARCHAR"}, {"name": "pop", "type": "BIGINT"}],
    "steps": [{"op": "select", "columns": ["code", "pop"]}],
    "provenance": {
        "connector": "upload",
        "fetched_at": "2026-11-27T10:00:00+00:00",
        "licence": "lov2",
        "producer": "Conseil départemental du Finistère",
        "url": "https://www.data.gouv.fr/datasets/population-des-communes-du-finistere",
    },
    "fingerprint": "abc",
}


@pytest.fixture
def alice(test_db):
    return create_user(test_db, email="alice@test.local", password="pw12345")


@pytest.fixture
def hub():
    return InMemoryHub(account="alice")


def _run(test_db, alice, **draft):
    data = {**DRAFT, **draft}
    run = JobRun(
        id="run-1",
        job_id="recipe",
        owner_id=alice.id,
        status="succeeded",
        options={"recipe_id": "rec-1"},
        draft=data,
    )
    test_db.add(run)
    test_db.commit()
    path = get_store().data_path(alice.id, "run-1")
    pq.write_table(pa.table({"code": ["29001", "29002"], "pop": [998, 1376]}), path)
    return run


CREDS = make_creds(hf_token="hf_" + "t" * 34)


def test_publishes_parquet_card_and_manifest_in_one_commit(test_db, alice, hub):
    run = _run(test_db, alice)
    published = publish(test_db, CREDS, run, backend=hub)
    files = hub.files("alice/communes")
    assert {"data/train-00000-of-00001.parquet", "README.md", "manifest.json"} <= set(
        files
    )
    assert hub.log("alice/communes")[-1].startswith("Publish 2 rows")
    table = pq.read_table(io.BytesIO(files["data/train-00000-of-00001.parquet"]))
    assert table.num_rows == 2
    manifest = json.loads(files["manifest.json"])
    assert manifest["kind"] == "table" and manifest["run_id"] == "run-1"
    assert len(manifest["files"][0]["sha256"]) == 64
    assert hub.is_private("alice/communes") is True
    assert run.status == "published" and run.published_url == published["url"]
    publication = test_db.query(Publication).one()
    assert (
        publication.commit_sha == published["commit"]
        and publication.visibility == "private"
    )


def test_the_card_validates_and_carries_the_attribution():
    card = tabular_card("alice/communes", DRAFT)
    parsed = DatasetCard(card)
    front = parsed.data.to_dict()
    assert front["license"] == "etalab-2.0"
    assert "dataset-generator" in front["tags"]
    configs = front["configs"]
    assert configs[0]["data_files"][0]["path"] == "data/*.parquet"
    assert "Source: Conseil départemental du Finistère — communes — 2026-11-27" in card
    assert "Keep the columns `code`, `pop`" in card


def test_a_second_publication_replaces_the_shards(test_db, alice, hub):
    run = _run(test_db, alice)
    publish(test_db, CREDS, run, backend=hub)
    hub.push(
        "alice/communes", {"data/train-00000-of-00002.parquet": b"old"}, message="x"
    )
    run.status = "succeeded"
    test_db.commit()
    publish(test_db, CREDS, run, backend=hub)
    assert "data/train-00000-of-00002.parquet" not in hub.files("alice/communes")


def test_a_moved_dataset_is_refused(test_db, alice, hub):
    run = _run(test_db, alice)
    hub.push("alice/communes", {"README.md": b"---\ntags:\n- dataset-generator\n---\n"})
    hub.before_commit.append(
        lambda: hub.push("alice/communes", {"other.txt": b"meanwhile"})
    )
    with pytest.raises(DatasetMoved):
        publish(test_db, CREDS, run, backend=hub)


def test_a_repo_the_app_did_not_make_is_left_alone(test_db, alice, hub):
    run = _run(test_db, alice)
    hub.push("alice/communes", {"README.md": b"---\nlicense: mit\n---\n# Mine\n"})
    with pytest.raises(RepoNotOurs):
        publish(test_db, CREDS, run, backend=hub)


def test_a_private_publication_needs_a_private_repo(test_db, alice, hub):
    run = _run(test_db, alice)
    hub.push("alice/communes", {"x.txt": b""}, private=False)
    with pytest.raises(RepoNotPrivate):
        publish(test_db, CREDS, run, backend=hub)


def test_public_when_the_licence_allows_it(test_db, alice, hub):
    run = _run(test_db, alice, visibility="public")
    published = publish(test_db, CREDS, run, backend=hub)
    assert published["visibility"] == "public"
    assert hub.is_private("alice/communes") is False


@pytest.mark.parametrize(
    "licence", [None, "notspecified", "other-at", "tous droits réservés"]
)
def test_public_is_refused_without_a_redistributable_licence(
    test_db, alice, hub, licence
):
    provenance = {**DRAFT["provenance"], "licence": licence}
    run = _run(test_db, alice, visibility="public", provenance=provenance)
    with pytest.raises(PublishRefused):
        publish(test_db, CREDS, run, backend=hub)
    assert not hub.exists("alice/communes")


@pytest.mark.parametrize(
    "stated,hf",
    [
        ("lov2", "etalab-2.0"),
        ("fr-lo", "etalab-2.0"),
        ("Licence Ouverte 2.0", "etalab-2.0"),
        ("odc-odbl", "odbl"),
        ("ODbL", "odbl"),
        ("odc-by", "odc-by"),
        ("cc-by", "cc-by-4.0"),
        ("CC-BY-SA 4.0", "cc-by-sa-4.0"),
        ("cc-zero", "cc0-1.0"),
        ("notspecified", "unknown"),
        ("other-pd", "other"),
        (None, "unknown"),
    ],
)
def test_licence_mapping(stated, hf):
    assert resolve(stated).hf == hf
    assert (public_refusal(stated) is None) == resolve(stated).redistributable
