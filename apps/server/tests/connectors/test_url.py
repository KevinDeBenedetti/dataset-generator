"""The URL connector (connectors/url.py): formats, unpacking, fingerprints,
the secret header, and the outbound guard (no network: a fake DNS and a mock
transport behind the real pinned one)."""

import asyncio
import gzip
import io
import socket
import zipfile
from pathlib import Path

import httpx2
import pytest

from server.connectors import http
from server.connectors.base import ConnectorError, Limits
from server.connectors.url import UrlConfig, UrlConnector, conditional_headers
from server.core import net
from server.core.net import PinnedTransport
from server.tests.creds import NONE

DATA = Path(__file__).resolve().parent.parent / "fixtures" / "data"
PUBLIC = "93.184.216.34"
CSV = (DATA / "communes-finistere-cp1252.csv").read_bytes()


class Site:
    def __init__(self):
        self.routes = {}
        self.seen = []

    def handler(self, request):
        self.seen.append(request)
        key = request.headers.get("host", "") + request.url.path
        route = self.routes.get(key)
        if route is None:
            return httpx2.Response(404)
        return route(request)


@pytest.fixture
def dns(monkeypatch):
    table = {"data.example.org": [PUBLIC], "cdn.example.org": [PUBLIC]}

    async def fake(host, port):
        if host not in table:
            raise socket.gaierror("unknown host")
        return list(table[host])

    monkeypatch.setattr(net, "resolve", fake)
    return table


@pytest.fixture
def site(monkeypatch, dns):
    fake = Site()

    def factory(allowed_hosts):
        return httpx2.AsyncClient(
            transport=PinnedTransport(
                allowed_hosts=allowed_hosts, inner=httpx2.MockTransport(fake.handler)
            ),
            follow_redirects=False,
        )

    monkeypatch.setattr(http, "client_factory", factory)
    return fake


def fetch(config, tmp_path, max_bytes=10**8, source_id="0" * 32, owner="alice"):
    return asyncio.run(
        UrlConnector().fetch(
            owner, source_id, config, NONE, tmp_path / "raw", Limits(max_bytes)
        )
    )


def serve(site, path, body, **headers):
    site.routes[f"data.example.org{path}"] = lambda r: httpx2.Response(
        200, content=body, headers=headers
    )


def test_a_csv_link(site, tmp_path):
    serve(site, "/communes.csv", CSV, **{"Content-Type": "text/csv", "ETag": '"v1"'})
    result = fetch({"url": "https://data.example.org/communes.csv"}, tmp_path)
    assert result.format == "csv"
    assert result.options == {"encoding": "cp1252", "delimiter": ";"}
    assert result.provenance.url == "https://data.example.org/communes.csv"
    assert UrlConnector().fingerprint(result) == 'etag:"v1"'


def test_the_content_type_beats_a_missing_extension(site, tmp_path):
    serve(
        site, "/export", b'[{"a": 1}, {"a": 2}]', **{"Content-Type": "application/json"}
    )
    assert fetch({"url": "https://data.example.org/export"}, tmp_path).format == "json"


def test_a_gzip_is_unpacked(site, tmp_path):
    serve(
        site,
        "/communes.csv.gz",
        gzip.compress(CSV),
        **{"Content-Type": "application/gzip"},
    )
    result = fetch({"url": "https://data.example.org/communes.csv.gz"}, tmp_path)
    assert result.format == "csv" and result.files[0].read_bytes() == CSV


def test_a_zip_of_one_file_is_unpacked(site, tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("communes.csv", CSV)
    serve(site, "/communes.zip", buffer.getvalue())
    result = fetch({"url": "https://data.example.org/communes.zip"}, tmp_path)
    assert result.format == "csv" and result.files[0].name == "unzipped-communes.csv"


def test_a_zip_of_several_files_is_refused(site, tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("a.csv", CSV)
        archive.writestr("b.csv", CSV)
    serve(site, "/two.zip", buffer.getvalue())
    with pytest.raises(ConnectorError, match="holds 2 files"):
        fetch({"url": "https://data.example.org/two.zip"}, tmp_path)


def test_a_zip_bomb_is_refused(site, tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("zeros.csv", b"0" * (40 * 1024 * 1024))
    serve(site, "/bomb.zip", buffer.getvalue())
    with pytest.raises(ConnectorError, match="expands too much"):
        fetch({"url": "https://data.example.org/bomb.zip"}, tmp_path)
    assert not list((tmp_path / "raw").glob("unzipped-*"))


def test_an_excel_workbook_is_not_unzipped(site, tmp_path):
    serve(site, "/communes.xlsx", (DATA / "communes.xlsx").read_bytes())
    assert (
        fetch({"url": "https://data.example.org/communes.xlsx"}, tmp_path).format
        == "xlsx"
    )


def test_a_redirect_on_the_same_site_is_followed(site, tmp_path):
    site.routes["data.example.org/latest.csv"] = lambda r: httpx2.Response(
        302, headers={"Location": "https://cdn.example.org/files/communes.csv"}
    )
    site.routes["cdn.example.org/files/communes.csv"] = lambda r: httpx2.Response(
        200, content=CSV
    )
    assert (
        fetch({"url": "https://data.example.org/latest.csv"}, tmp_path).format == "csv"
    )


class TestOutboundGuard:
    def test_http_is_refused(self):
        with pytest.raises(ValueError, match="https"):
            UrlConfig(url="http://data.example.org/x.csv")

    def test_credentials_in_the_url_are_refused(self):
        with pytest.raises(ValueError, match="credentials"):
            UrlConfig(url="https://user:pw@data.example.org/x.csv")

    def test_a_private_address_is_refused(self, site, tmp_path):
        with pytest.raises(ConnectorError, match="non-public"):
            fetch({"url": "https://127.0.0.1/x.csv"}, tmp_path)

    def test_dns_rebinding_to_a_private_address_is_refused(self, site, dns, tmp_path):
        dns["data.example.org"] = ["10.0.0.7"]
        with pytest.raises(ConnectorError, match="non-public"):
            fetch({"url": "https://data.example.org/x.csv"}, tmp_path)

    def test_a_redirect_to_the_metadata_address_is_refused(self, site, tmp_path):
        site.routes["data.example.org/x.csv"] = lambda r: httpx2.Response(
            302, headers={"Location": "https://169.254.169.254/latest/meta-data/"}
        )
        with pytest.raises(ConnectorError, match="another site"):
            fetch({"url": "https://data.example.org/x.csv"}, tmp_path)
        assert all(r.url.host != "169.254.169.254" for r in site.seen)

    def test_a_redirect_to_another_site_is_refused(self, site, tmp_path):
        site.routes["data.example.org/x.csv"] = lambda r: httpx2.Response(
            302, headers={"Location": "https://elsewhere.example.net/x.csv"}
        )
        with pytest.raises(ConnectorError, match="another site"):
            fetch({"url": "https://data.example.org/x.csv"}, tmp_path)

    def test_an_oversize_file_stops(self, site, tmp_path):
        serve(site, "/big.csv", CSV)
        with pytest.raises(ConnectorError, match="larger than"):
            fetch({"url": "https://data.example.org/big.csv"}, tmp_path, max_bytes=100)


class TestRefresh:
    def test_a_304_means_unchanged(self, site):
        def answer(request):
            if request.headers.get("if-none-match") == '"v1"':
                return httpx2.Response(304)
            return httpx2.Response(200, headers={"ETag": '"v2"'})

        site.routes["data.example.org/communes.csv"] = answer
        connector = UrlConnector()
        config = {"url": "https://data.example.org/communes.csv"}
        assert (
            asyncio.run(connector.unchanged("alice", "s", config, 'etag:"v1"')) is True
        )
        assert (
            asyncio.run(connector.unchanged("alice", "s", config, 'etag:"v0"')) is False
        )
        assert site.seen[0].method == "HEAD"

    def test_conditional_headers(self):
        assert conditional_headers('etag:"x"') == {"If-None-Match": '"x"'}
        lm = "Wed, 01 Jan 2026 00:00:00 GMT"
        assert conditional_headers(f"lm:{lm}|10") == {"If-Modified-Since": lm}
        assert conditional_headers("sha256:abc") == {}

    def test_a_weak_etag_falls_back_to_last_modified(self, site, tmp_path):
        serve(
            site,
            "/c.csv",
            CSV,
            **{"ETag": 'W/"x"', "Last-Modified": "Wed, 01 Jan 2026 00:00:00 GMT"},
        )
        result = fetch({"url": "https://data.example.org/c.csv"}, tmp_path)
        assert UrlConnector().fingerprint(result).startswith("lm:Wed, 01 Jan 2026")


class TestSecretHeader:
    @pytest.fixture
    def alice(self, test_db, datasets_db):
        from server.services.users import create_user

        return create_user(test_db, email="alice@test.local", password="pw12345")

    def test_the_header_is_sent_and_never_shown(
        self, site, tmp_path, alice, client_for
    ):
        site.routes["data.example.org/private.csv"] = lambda r: (
            httpx2.Response(200, content=CSV)
            if r.headers.get("authorization") == "Bearer s3cr3t-value"
            else httpx2.Response(401)
        )
        api = client_for(alice)
        source = api.post(
            "/data-sources",
            json={
                "name": "Private",
                "connector": "url",
                "config": {
                    "url": "https://data.example.org/private.csv",
                    "header_name": "Authorization",
                },
            },
        ).json()
        with pytest.raises(ConnectorError, match="not saved"):
            fetch(source["config"], tmp_path, source_id=source["id"], owner=alice.id)
        resp = api.put(
            f"/data-sources/{source['id']}/secret",
            json={"value": "Bearer s3cr3t-value"},
        )
        assert resp.status_code == 200 and resp.json() == {"configured": True}
        result = fetch(
            source["config"], tmp_path, source_id=source["id"], owner=alice.id
        )
        assert "s3cr3t" not in repr(result.provenance.to_dict())
        listed = api.get(f"/data-sources/{source['id']}").text
        assert "s3cr3t" not in listed
        assert api.delete(f"/data-sources/{source['id']}/secret").status_code == 204
        upload = api.post(
            "/data-sources/upload",
            files={"file": ("a.csv", b"a\n1\n")},
            data={"name": "Up"},
        ).json()
        assert (
            api.put(
                f"/data-sources/{upload['id']}/secret", json={"value": "x"}
            ).status_code
            == 422
        )
