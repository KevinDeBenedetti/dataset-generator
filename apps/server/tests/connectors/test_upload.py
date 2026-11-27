"""The upload connector (connectors/upload.py) and its route."""

import asyncio
from pathlib import Path

import pytest

from server.connectors.base import ConnectorError, Limits
from server.connectors.sniff import sniff
from server.connectors.upload import UploadConnector
from server.core.config import config
from server.services.users import create_user
from server.tests.creds import NONE

DATA = Path(__file__).resolve().parent.parent / "fixtures" / "data"


class TestSniff:
    @pytest.mark.parametrize(
        "name,fmt",
        [
            ("communes.tsv", "tsv"),
            ("communes.json", "json"),
            ("communes.jsonl", "jsonl"),
            ("communes.parquet", "parquet"),
            ("communes.xlsx", "xlsx"),
        ],
    )
    def test_each_format_is_recognised(self, name, fmt):
        assert sniff(DATA / name, name).format == fmt

    def test_utf8_with_a_bom_and_semicolons(self):
        name = "communes-finistere-utf8bom.csv"
        found = sniff(DATA / name, name)
        assert found.format == "csv"
        assert found.options == {"encoding": "utf-8-sig", "delimiter": ";"}

    def test_windows_1252_with_semicolons(self):
        name = "communes-finistere-cp1252.csv"
        found = sniff(DATA / name, name)
        assert found.options == {"encoding": "cp1252", "delimiter": ";"}

    def test_a_csv_named_json_is_refused(self, tmp_path):
        mislabelled = tmp_path / "communes.json"
        mislabelled.write_bytes((DATA / "communes-finistere-utf8bom.csv").read_bytes())
        with pytest.raises(ConnectorError, match="not JSON"):
            sniff(mislabelled, "communes.json")

    def test_a_parquet_named_csv_is_refused(self, tmp_path):
        mislabelled = tmp_path / "x.csv"
        mislabelled.write_bytes((DATA / "communes.parquet").read_bytes())
        with pytest.raises(ConnectorError, match="PARQUET, not CSV"):
            sniff(mislabelled, "x.csv")

    def test_the_form_overrides_what_was_detected(self):
        name = "communes-finistere-utf8bom.csv"
        found = sniff(DATA / name, name, {"delimiter": ",", "encoding": "latin-1"})
        assert found.options == {"encoding": "latin-1", "delimiter": ","}

    def test_an_empty_file_is_refused(self, tmp_path):
        empty = tmp_path / "e.csv"
        empty.write_bytes(b"")
        with pytest.raises(ConnectorError, match="empty"):
            sniff(empty, "e.csv")


@pytest.fixture
def alice(test_db):
    return create_user(test_db, email="alice@test.local", password="pw12345")


def _upload(client, name, data=None, **form):
    payload = data if data is not None else (DATA / name).read_bytes()
    return client.post(
        "/data-sources/upload",
        files={"file": (name, payload)},
        data={"name": form.pop("label", name), **form},
    )


class TestRoute:
    def test_uploads_and_describes_the_file(self, alice, client_for):
        api = client_for(alice)
        name = "communes-finistere-cp1252.csv"
        resp = _upload(api, name, licence="Licence Ouverte 2.0")
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["connector"] == "upload"
        assert body["licence"] == "Licence Ouverte 2.0"
        assert body["config"]["format"] == "csv"
        assert body["config"]["options"] == {"encoding": "cp1252", "delimiter": ";"}
        assert len(body["config"]["sha256"]) == 64

    @pytest.mark.parametrize(
        "name",
        [
            "communes.tsv",
            "communes.json",
            "communes.jsonl",
            "communes.parquet",
            "communes.xlsx",
        ],
    )
    def test_every_format_uploads(self, alice, client_for, name):
        resp = _upload(client_for(alice), name)
        assert resp.status_code == 201, resp.text
        assert resp.json()["config"]["format"] == name.rsplit(".", 1)[1]

    def test_a_mislabelled_file_is_refused_and_leaves_nothing(self, alice, client_for):
        from server.services.draft_store import get_store

        data = (DATA / "communes-finistere-utf8bom.csv").read_bytes()
        resp = _upload(client_for(alice), "communes.json", data=data)
        assert resp.status_code == 422
        assert "not JSON" in resp.json()["detail"]
        assert get_store().size(alice.id) == 0
        assert client_for(alice).get("/data-sources").json()["data_sources"] == []

    def test_an_oversize_upload_is_refused(self, alice, client_for, monkeypatch):
        monkeypatch.setattr(config, "data_upload_max_bytes", 1000)
        resp = _upload(client_for(alice), "communes.json")
        assert resp.status_code == 413

    def test_the_body_limit_refuses_it_before_reading(
        self, alice, client_for, monkeypatch
    ):
        """A declared Content-Length over the path's limit never reaches the route."""
        from server.core.http_security import BodySizeLimitMiddleware

        captured = {}
        original = BodySizeLimitMiddleware.__init__

        def spy(self, app, max_body_bytes, per_path=None):
            original(self, app, max_body_bytes, per_path)
            captured.update(self.per_path)

        monkeypatch.setattr(BodySizeLimitMiddleware, "__init__", spy)
        client_for(alice)  # builds the app
        assert captured["/data-sources/upload"] > config.max_request_body_bytes

    def test_a_file_data_source_is_only_made_by_an_upload(self, alice, client_for):
        resp = client_for(alice).post(
            "/data-sources", json={"name": "x", "connector": "upload", "config": {}}
        )
        assert resp.status_code == 422

    def test_another_user_cannot_see_or_fetch_it(
        self, alice, client_for, test_db, tmp_path
    ):
        bob = create_user(test_db, email="bob@test.local", password="pw12345")
        source = _upload(client_for(alice), "communes.json").json()
        bobs = client_for(bob)
        assert bobs.get(f"/data-sources/{source['id']}").status_code == 404
        assert bobs.get("/data-sources").json()["data_sources"] == []
        with pytest.raises(ConnectorError, match="gone"):
            asyncio.run(
                UploadConnector().fetch(
                    bob.id,
                    source["id"],
                    source["config"],
                    NONE,
                    tmp_path,
                    Limits(10**9),
                )
            )

    def test_fetch_copies_the_file_and_fingerprints_it(
        self, alice, client_for, tmp_path
    ):
        source = _upload(client_for(alice), "communes.parquet").json()
        connector = UploadConnector()
        result = asyncio.run(
            connector.fetch(
                alice.id,
                source["id"],
                source["config"],
                NONE,
                tmp_path / "raw",
                Limits(10**9),
            )
        )
        assert result.format == "parquet" and result.files[0].is_file()
        assert connector.fingerprint(result) == source["config"]["sha256"]
        assert result.provenance.connector == "upload"

    def test_connectors_are_listed_in_your_language(self, alice, client_for):
        resp = client_for(alice).get("/connectors", headers={"Accept-Language": "fr"})
        [upload] = [c for c in resp.json()["connectors"] if c["kind"] == "upload"]
        assert upload["title"] == "Envoi de fichier" and upload["created_by_upload"]
