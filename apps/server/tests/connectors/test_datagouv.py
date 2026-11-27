"""The data.gouv.fr connector (connectors/datagouv.py) on recorded answers
(tests/fixtures/datagouv): no network."""

import asyncio
import json
from pathlib import Path

import httpx2
import pytest

from server.connectors import http
from server.connectors.base import ConnectorError, Limits
from server.connectors.datagouv import DatagouvConnector
from server.tests.creds import NONE

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
DG = FIXTURES / "datagouv"
DATASET_ID = "62b25c51ea3141106f538362"
CSV_ID = "984916d0-18e3-439e-a795-352f10389e4f"
CSV_URL = (
    "https://static.data.gouv.fr/resources/population-des-communes-du-finistere/"
    "20250103-152649/population-des-communes-du-finistere.csv"
)


def load(name):
    return json.loads((DG / name).read_text())


class FakeWeb:
    """Routes of the recorded answers; ``calls`` keeps what was asked."""

    def __init__(self):
        self.calls = []
        self.routes = {}
        self.add_json(
            f"https://www.data.gouv.fr/api/1/datasets/{DATASET_ID}/",
            load("dataset.json"),
        )
        self.add_json("https://www.data.gouv.fr/api/1/datasets/", load("search.json"))
        self.add_json(
            f"https://tabular-api.data.gouv.fr/api/resources/{CSV_ID}/profile/",
            load("profile.json"),
        )
        self.routes[CSV_URL] = lambda request: httpx2.Response(
            200,
            content=(FIXTURES / "data" / "communes-finistere-utf8bom.csv").read_bytes(),
        )

    def add_json(self, url, body, status=200, headers=None):
        self.routes[url] = lambda request: httpx2.Response(
            status, json=body, headers=headers or {}
        )

    def handler(self, request):
        url = str(request.url).split("?")[0]
        self.calls.append(str(request.url))
        route = self.routes.get(url)
        if route is None:
            return httpx2.Response(404, json={"message": "not found"})
        return route(request)


@pytest.fixture
def web(monkeypatch):
    fake = FakeWeb()

    def factory(allowed_hosts):
        return httpx2.AsyncClient(
            transport=httpx2.MockTransport(fake.handler), follow_redirects=False
        )

    monkeypatch.setattr(http, "client_factory", factory)

    async def no_wait(_seconds):
        return None

    monkeypatch.setattr(http.asyncio, "sleep", no_wait)
    return fake


def run(coro):
    return asyncio.run(coro)


def fetch(config, tmp_path, max_bytes=10**8):
    return run(
        DatagouvConnector().fetch(
            "alice", "s1", config, NONE, tmp_path / "raw", Limits(max_bytes)
        )
    )


def test_search_lists_datasets_and_their_readable_resources(web):
    [found] = run(DatagouvConnector().discover("communes finistère", NONE))
    assert found.title == "Population des communes du Finistère"
    assert found.extra["organization"] == "Conseil départemental du Finistère"
    assert found.extra["licence"] == "lov2"
    resources = {r["format"]: r for r in found.extra["resources"]}
    assert set(resources) == {"csv", "xlsx", "parquet"}
    assert resources["csv"]["tabular_api"] is True
    assert resources["xlsx"]["tabular_api"] is False  # the API failed to parse it
    assert "q=communes" in web.calls[0]


def test_file_mode_reads_the_csv_with_the_profile_hints(web, tmp_path):
    result = fetch({"dataset_id": DATASET_ID, "resource_id": CSV_ID}, tmp_path)
    assert result.format == "csv"
    assert result.options == {"encoding": "utf-8-sig", "delimiter": ";"}
    p = result.provenance
    assert p.producer == "Conseil départemental du Finistère"
    assert p.licence == "lov2" and p.resource_id == CSV_ID
    assert (
        p.url
        == "https://www.data.gouv.fr/datasets/population-des-communes-du-finistere"
    )
    assert p.last_modified is not None and p.last_modified.year == 2025
    assert DatagouvConnector().fingerprint(result).startswith("sha1:36bd88c5")


def test_a_redirect_to_static_data_gouv_is_followed(web, tmp_path):
    short = f"https://www.data.gouv.fr/fr/datasets/r/{CSV_ID}"
    dataset = load("dataset.json")
    dataset["resources"][0]["url"] = short
    web.add_json(f"https://www.data.gouv.fr/api/1/datasets/{DATASET_ID}/", dataset)
    web.routes[short] = lambda r: httpx2.Response(302, headers={"Location": CSV_URL})
    result = fetch({"dataset_id": DATASET_ID, "resource_id": CSV_ID}, tmp_path)
    assert result.files[0].stat().st_size > 0


def test_a_redirect_elsewhere_is_refused(web, tmp_path):
    web.routes[CSV_URL] = lambda r: httpx2.Response(
        302, headers={"Location": "https://evil.example/steal"}
    )
    with pytest.raises(ConnectorError, match="not a host"):
        fetch({"dataset_id": DATASET_ID, "resource_id": CSV_ID}, tmp_path)


def test_a_resource_hosted_elsewhere_needs_the_url_connector(web, tmp_path):
    dataset = load("dataset.json")
    dataset["resources"][0]["url"] = "https://opendata.example.org/communes.csv"
    web.add_json(f"https://www.data.gouv.fr/api/1/datasets/{DATASET_ID}/", dataset)
    with pytest.raises(ConnectorError, match="outside data.gouv.fr"):
        fetch({"dataset_id": DATASET_ID, "resource_id": CSV_ID}, tmp_path)


def test_file_mode_without_the_tabular_api(web, tmp_path):
    """A resource the tabular API doesn't know still downloads (profile 404)."""
    del web.routes[f"https://tabular-api.data.gouv.fr/api/resources/{CSV_ID}/profile/"]
    result = fetch({"dataset_id": DATASET_ID, "resource_id": CSV_ID}, tmp_path)
    assert result.options["delimiter"] == ";"  # sniffed instead


def test_tabular_mode_pages_through_the_rows_with_filters(web, tmp_path):
    data = f"https://tabular-api.data.gouv.fr/api/resources/{CSV_ID}/data/"
    second = load("data-page-1.json")["links"]["next"]
    web.add_json(data, load("data-page-1.json"))
    web.routes[second.split("?")[0]] = web.routes[data]
    pages = iter([load("data-page-1.json"), load("data-page-2.json")])
    web.routes[data] = lambda r: httpx2.Response(200, json=next(pages))
    config = {
        "dataset_id": DATASET_ID,
        "resource_id": CSV_ID,
        "mode": "tabular_api",
        "filters": [{"column": "canton", "op": "exact", "value": "Crozon"}],
    }
    result = fetch(config, tmp_path)
    rows = [json.loads(line) for line in result.files[0].read_text().splitlines()]
    assert result.format == "jsonl" and len(rows) == 5
    assert "__id" not in rows[0]
    assert "canton__exact=Crozon" in web.calls[1] and "page_size=200" in web.calls[1]


def test_a_rate_limit_is_retried_then_reported(web, tmp_path):
    url = f"https://www.data.gouv.fr/api/1/datasets/{DATASET_ID}/"
    web.add_json(url, {}, status=429, headers={"Retry-After": "1"})
    with pytest.raises(ConnectorError, match="limits how often"):
        fetch({"dataset_id": DATASET_ID, "resource_id": CSV_ID}, tmp_path)
    assert sum(1 for c in web.calls if c.startswith(url)) == http.MAX_RETRIES + 1


def test_an_unreachable_api_says_so(web, tmp_path, monkeypatch):
    def down(request):
        raise httpx2.ConnectError("refused", request=request)

    monkeypatch.setattr(
        http,
        "client_factory",
        lambda hosts: httpx2.AsyncClient(transport=httpx2.MockTransport(down)),
    )
    with pytest.raises(ConnectorError, match="could not be reached"):
        fetch({"dataset_id": DATASET_ID, "resource_id": CSV_ID}, tmp_path)


def test_an_oversize_download_stops(web, tmp_path):
    with pytest.raises(ConnectorError, match="larger than"):
        fetch(
            {"dataset_id": DATASET_ID, "resource_id": CSV_ID}, tmp_path, max_bytes=100
        )
    assert not list((tmp_path / "raw").glob("*.csv"))


def test_the_api_routes(web, client_for, test_db):
    from server.services.users import create_user

    alice = create_user(test_db, email="alice@test.local", password="pw12345")
    api = client_for(alice)
    found = api.get("/connectors/datagouv/discover", params={"q": "communes"}).json()
    assert found["candidates"][0]["extra"]["dataset_id"] == DATASET_ID
    profile = api.get(f"/connectors/datagouv/resources/{CSV_ID}/profile").json()
    assert profile["separator"] == ";"
    assert api.get("/connectors/upload/discover", params={"q": "xx"}).status_code == 404
    created = api.post(
        "/data-sources",
        json={
            "name": "Finistère",
            "connector": "datagouv",
            "config": {"dataset_id": DATASET_ID, "resource_id": CSV_ID},
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["config"]["mode"] == "file"


def test_from_data_gouv_to_a_published_card(web, client_for, test_db, datasets_db):
    """Search → data source → run → publish: the card names the producer, the
    licence and the retrieval date."""
    from server.jobs.registry import JOBS, TabularRecipeOptions
    from server.models.job_run import JobRun
    from server.services import queue, user_secrets
    from server.services.credentials import resolve_credentials
    from server.services.tabular_publish import publish
    from server.services.users import create_user
    from server.tests.fake_hub import InMemoryHub

    alice = create_user(test_db, email="alice@test.local", password="pw12345")
    user_secrets.set_secret(alice.id, "hf_token", "hf_" + "t" * 34)
    api = client_for(alice, real_credentials=True)
    source = api.post(
        "/data-sources",
        json={
            "name": "Finistère",
            "connector": "datagouv",
            "config": {"dataset_id": DATASET_ID, "resource_id": CSV_ID},
        },
    ).json()
    recipe = api.post(
        "/recipes",
        json={
            "name": "Finistère",
            "data_source_id": source["id"],
            "target_repo": "alice/finistere",
            "visibility": "public",
        },
    ).json()

    async def go():
        return await JOBS["recipe"].runner(
            resolve_credentials(alice.id),
            TabularRecipeOptions(recipe_id=recipe["id"]),
            None,
            lambda *a: None,
        )

    token = queue._current_run.set("run-dg")
    try:
        draft = asyncio.run(go()).draft
    finally:
        queue._current_run.reset(token)
    run = JobRun(
        id="run-dg",
        job_id="recipe",
        owner_id=alice.id,
        status="succeeded",
        options={"recipe_id": recipe["id"]},
        draft=draft,
    )
    test_db.add(run)
    test_db.commit()
    hub = InMemoryHub(account="alice")
    publish(test_db, resolve_credentials(alice.id), run, backend=hub)
    card = hub.files("alice/finistere")["README.md"].decode()
    assert "license: etalab-2.0" in card
    attribution = (
        "Source: Conseil départemental du Finistère — Population des communes du "
        "Finistère — 2025-01-03"
    )
    assert attribution in card
    assert "Retrieved: " in card
    assert hub.is_private("alice/finistere") is False
