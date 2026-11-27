"""The REST connector (connectors/rest.py) against a local fake API: every
pagination type, the limits, the API key — no network."""

import asyncio
import json
import logging

import httpx2
import pytest

from server.connectors import http
from server.connectors.base import ConnectorError, Limits
from server.connectors.rest import RestConfig, RestConnector, flatten, json_path
from server.tests.creds import NONE

ITEMS = [
    {"id": i, "nom": f"Commune {i}", "geo": {"lat": 48.0 + i, "tags": ["a"]}}
    for i in range(1, 8)
]
BASE = "https://api.example.gouv.fr/v1/items"


class FakeApi:
    """A paging API over ITEMS; ``mode`` picks how it pages."""

    def __init__(self, mode, size=3):
        self.mode = mode
        self.size = size
        self.requests = []

    def handler(self, request):
        self.requests.append(request)
        q = dict(request.url.params)
        if self.mode == "page":
            page = int(q.get("page", 1))
            chunk = ITEMS[(page - 1) * self.size : page * self.size]
            return httpx2.Response(200, json={"results": chunk, "total": len(ITEMS)})
        if self.mode == "offset":
            offset = int(q.get("offset", 0))
            return httpx2.Response(
                200, json={"results": ITEMS[offset : offset + self.size]}
            )
        if self.mode == "cursor":
            start = int(q.get("cursor", 0))
            nxt = start + self.size if start + self.size < len(ITEMS) else None
            return httpx2.Response(
                200,
                json={
                    "data": {"items": ITEMS[start : start + self.size]},
                    "next_cursor": nxt,
                },
            )
        if self.mode == "link_header":
            start = int(q.get("from", 0))
            headers = {}
            if start + self.size < len(ITEMS):
                headers["Link"] = (
                    f'<{BASE}?from={start + self.size}>; rel="next", <{BASE}>; rel="first"'
                )
            return httpx2.Response(
                200, json=ITEMS[start : start + self.size], headers=headers
            )
        if self.mode == "next_url":
            start = int(q.get("from", 0))
            nxt = (
                f"{BASE}?from={start + self.size}"
                if start + self.size < len(ITEMS)
                else None
            )
            return httpx2.Response(
                200,
                json={
                    "results": ITEMS[start : start + self.size],
                    "links": {"next": nxt},
                },
            )
        return httpx2.Response(200, json=ITEMS)


@pytest.fixture
def api(monkeypatch):
    holder = {}

    def use(mode, size=3):
        fake = holder["api"] = FakeApi(mode, size)
        monkeypatch.setattr(
            http,
            "client_factory",
            lambda hosts: httpx2.AsyncClient(
                transport=httpx2.MockTransport(fake.handler)
            ),
        )
        return fake

    async def no_sleep(_s):
        return None

    monkeypatch.setattr("server.connectors.rest.asyncio.sleep", no_sleep)
    return use


def fetch(config, tmp_path, max_bytes=10**8, owner="alice", source_id="0" * 32):
    return asyncio.run(
        RestConnector().fetch(
            owner, source_id, config, NONE, tmp_path / "raw", Limits(max_bytes)
        )
    )


def rows(result):
    return [json.loads(line) for line in result.files[0].read_text().splitlines()]


@pytest.mark.parametrize(
    "mode,pagination,records_path",
    [
        ("none", {"type": "none"}, "$"),
        ("page", {"type": "page", "size_param": "per_page", "size": 3}, "$.results"),
        ("offset", {"type": "offset", "size_param": "limit", "size": 3}, "$.results"),
        ("cursor", {"type": "cursor", "cursor_path": "$.next_cursor"}, "$.data.items"),
        ("link_header", {"type": "link_header"}, "$"),
        (
            "next_url",
            {"type": "next_url", "next_url_path": "$.links.next"},
            "$.results",
        ),
    ],
)
def test_every_pagination_reads_every_record(
    api, tmp_path, mode, pagination, records_path
):
    fake = api(mode)
    config = {"url": BASE, "records_path": records_path, "pagination": pagination}
    result = fetch(config, tmp_path)
    assert [r["id"] for r in rows(result)] == list(range(1, 8))
    assert result.warnings == []
    if mode != "none":
        assert len(fake.requests) == 3


def test_records_are_flattened_one_level(api, tmp_path):
    api("none")
    first = rows(fetch({"url": BASE}, tmp_path))[0]
    assert first == {"id": 1, "nom": "Commune 1", "geo.lat": 49.0, "geo.tags": '["a"]'}
    assert flatten(3) == {"value": 3}


def test_limits_stop_with_a_warning(api, tmp_path):
    api("page")
    config = {
        "url": BASE,
        "records_path": "$.results",
        "pagination": {"type": "page", "size_param": "per_page", "size": 3},
        "max_pages": 2,
    }
    result = fetch(config, tmp_path)
    assert len(rows(result)) == 6
    assert result.warnings == ["Stopped after 2 pages (max_pages)"]
    config = {**config, "max_pages": 50, "max_records": 4}
    result = fetch(config, tmp_path)
    assert len(rows(result)) == 4
    assert result.warnings == ["Stopped at 4 records (max_records)"]


def test_the_fingerprint_is_the_first_page_and_total_when_given(api, tmp_path):
    api("page")
    config = {
        "url": BASE,
        "records_path": "$.results",
        "total_path": "$.total",
        "pagination": {"type": "page", "size_param": "per_page", "size": 3},
    }
    result = fetch(config, tmp_path)
    assert RestConnector().fingerprint(result).startswith(
        "first:"
    ) and result.version.endswith("|7")
    api("none")
    assert (
        RestConnector()
        .fingerprint(fetch({"url": BASE}, tmp_path))
        .startswith("sha256:")
    )


def test_a_next_page_on_another_site_is_refused(api, tmp_path, monkeypatch):
    def handler(request):
        return httpx2.Response(
            200,
            json=ITEMS[:1],
            headers={"Link": '<https://evil.example.net/p2>; rel="next"'},
        )

    monkeypatch.setattr(
        http,
        "client_factory",
        lambda hosts: httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    with pytest.raises(ConnectorError, match="another site"):
        fetch({"url": BASE, "pagination": {"type": "link_header"}}, tmp_path)


def test_a_503_is_retried(api, tmp_path, monkeypatch):
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) < 3:
            return httpx2.Response(503, headers={"Retry-After": "0"})
        return httpx2.Response(200, json=ITEMS)

    async def no_wait(_s):
        return None

    monkeypatch.setattr(http.asyncio, "sleep", no_wait)
    monkeypatch.setattr(
        http,
        "client_factory",
        lambda hosts: httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    assert len(rows(fetch({"url": BASE}, tmp_path))) == 7 and len(calls) == 3


@pytest.mark.parametrize(
    "config",
    [
        {"url": "http://api.example.gouv.fr/x"},
        {"url": BASE, "records_path": "results"},
        {"url": BASE, "auth": {"type": "header"}},
        {"url": BASE, "pagination": {"type": "cursor"}},
    ],
)
def test_bad_configs_are_refused(config):
    with pytest.raises(ValueError):
        RestConfig.model_validate(config)


def test_json_path():
    doc = {"a": {"b": [{"c": 1}]}}
    assert json_path(doc, "$.a.b[0].c") == 1
    assert json_path(doc, "$.a.x") is None and json_path(doc, "$") == doc


class TestApiKey:
    @pytest.fixture
    def alice(self, test_db, datasets_db):
        from server.services.users import create_user

        return create_user(test_db, email="alice@test.local", password="pw12345")

    @pytest.mark.parametrize("where", ["header", "query"])
    def test_the_key_is_sent_and_never_shown(
        self, api, tmp_path, alice, client_for, caplog, where
    ):
        fake = api("none")
        client = client_for(alice)
        source = client.post(
            "/data-sources",
            json={
                "name": f"API {where}",
                "connector": "rest",
                "config": {"url": BASE, "auth": {"type": where, "name": "X-API-KEY"}},
            },
        ).json()
        key = "k3y-S3CRET-value"
        assert (
            client.put(
                f"/data-sources/{source['id']}/secret", json={"value": key}
            ).status_code
            == 200
        )
        with caplog.at_level(logging.DEBUG):
            result = fetch(
                source["config"], tmp_path, owner=alice.id, source_id=source["id"]
            )
            tested = client.post(f"/data-sources/{source['id']}/test")
        sent = fake.requests[0]
        if where == "header":
            assert sent.headers["x-api-key"] == key
        else:
            assert sent.url.params["X-API-KEY"] == key
        assert tested.status_code == 200 and tested.json()["records"] == 7
        assert "geo.lat" in tested.json()["columns"]
        for text in (
            caplog.text,
            repr(result.provenance.to_dict()),
            tested.text,
            client.get(f"/data-sources/{source['id']}").text,
        ):
            assert key not in text

    def test_a_missing_key_says_so(self, api, tmp_path, alice, client_for):
        api("none")
        source = (
            client_for(alice)
            .post(
                "/data-sources",
                json={
                    "name": "API",
                    "connector": "rest",
                    "config": {
                        "url": BASE,
                        "auth": {"type": "header", "name": "X-API-KEY"},
                    },
                },
            )
            .json()
        )
        with pytest.raises(ConnectorError, match="API key is not saved"):
            fetch(source["config"], tmp_path, owner=alice.id, source_id=source["id"])
