"""Presets for French public APIs (connectors/presets): each one fetches its
recorded sample through the REST connector, with its licence, producer and
rate limit; the routes; Sirene's first steps. No network: the fixtures were
recorded from the live APIs (Sirene's is built from its OpenAPI schema)."""

import asyncio
import json
from pathlib import Path

import httpx2
import pytest

from server.connectors import http
from server.connectors.base import Limits
from server.connectors.presets import Preset, get_preset, presets
from server.connectors.rest import RestConfig, RestConnector
from server.tests.creds import NONE

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "presets"


def preset(preset_id: str) -> Preset:
    found = get_preset(preset_id)
    assert found is not None, preset_id
    return found


def _serve(monkeypatch, handler):
    monkeypatch.setattr(
        http,
        "client_factory",
        lambda hosts: httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )

    async def no_sleep(_s):
        return None

    monkeypatch.setattr("server.connectors.rest.asyncio.sleep", no_sleep)


def _fetch(config, tmp_path, monkeypatch, secret=None):
    if secret is not None:
        monkeypatch.setattr(
            "server.services.user_secrets.get_source_secret", lambda owner, kind: secret
        )
    result = asyncio.run(
        RestConnector().fetch("alice", "0" * 32, config, NONE, tmp_path, Limits(10**8))
    )
    return [json.loads(line) for line in result.files[0].read_text().splitlines()]


def test_every_preset_makes_a_valid_rest_config():
    samples = {
        "geo-communes": {"departement": "2A"},
        "geo-divisions": {"level": "regions"},
        "adresse-search": {"q": "rue de siam", "citycode": "29019"},
        "adresse-reverse": {"lat": 48.387, "lon": -4.4905},
        "annuaire-offices": {"departement": "29", "service": "mairie"},
        "sirene-establishments": {"q": "codeCommuneEtablissement:29019"},
    }
    assert set(samples) == set(presets())
    for preset_id, params in samples.items():
        made = preset(preset_id)
        config = RestConfig.model_validate(made.config(params))
        assert config.preset == preset_id and config.producer == made.producer
        assert config.rate_limit_per_s == made.rate_limit_per_s
        assert config.url.startswith("https://")


def test_geo_communes_fetch_the_sample(tmp_path, monkeypatch):
    sample = json.loads((FIXTURES / "geo_communes_2a.json").read_text())
    seen = []

    def handler(request):
        seen.append(request.url)
        return httpx2.Response(200, json=sample)

    _serve(monkeypatch, handler)
    config = preset("geo-communes").config({"departement": "2A"})
    rows = _fetch(config, tmp_path, monkeypatch)
    assert [r["code"] for r in rows] == ["2A001", "2A004", "2A006"]
    assert seen[0].path == "/departements/2A/communes"


def test_adresse_search_flattens_the_features(tmp_path, monkeypatch):
    sample = json.loads((FIXTURES / "ban_search.json").read_text())
    _serve(monkeypatch, lambda request: httpx2.Response(200, json=sample))
    config = preset("adresse-search").config({"q": "rue de siam", "citycode": "29019"})
    assert config["params"]["citycode"] == "29019"
    rows = _fetch(config, tmp_path, monkeypatch)
    assert rows[0]["properties.label"] == "Rue de Siam 29200 Brest"


def test_annuaire_pages_by_offset_and_stops_at_its_depth(tmp_path, monkeypatch):
    sample = json.loads((FIXTURES / "annuaire_29.json").read_text())
    offsets = []

    def handler(request):
        q = dict(request.url.params)
        offsets.append(int(q["offset"]))
        assert int(q["offset"]) + int(q["limit"]) <= 10_000
        assert "affectation_personne" not in q["select"]
        record = sample["results"][0]
        return httpx2.Response(
            200, json={"total_count": 20_000, "results": [record] * int(q["limit"])}
        )

    _serve(monkeypatch, handler)
    config = preset("annuaire-offices").config({"departement": "29"})
    # Edited to page deeper: the preset's cap still holds.
    config["max_records"] = 50_000
    rows = _fetch(RestConfig.model_validate(config).model_dump(), tmp_path, monkeypatch)
    assert len(rows) == 10_000 and offsets[-1] == 9_900


def test_sirene_pages_with_its_cursor_and_sends_the_key(tmp_path, monkeypatch):
    def establishment(n):
        return {
            "siret": f"0000000000{n:04d}",
            "uniteLegale": {
                "nomUniteLegale": None,
                "denominationUniteLegale": f"Société {n}",
            },
        }

    pages = {"*": ("c1", [1, 2]), "c1": ("c2", [3]), "c2": ("c2", [])}
    keys = []

    def handler(request):
        keys.append(request.headers.get("X-INSEE-Api-Key-Integration"))
        cursor = dict(request.url.params)["curseur"]
        nxt, ids = pages[cursor]
        return httpx2.Response(
            200,
            json={
                "header": {"total": 3, "curseur": cursor, "curseurSuivant": nxt},
                "etablissements": [establishment(i) for i in ids],
            },
        )

    _serve(monkeypatch, handler)
    config = preset("sirene-establishments").config(
        {"q": "codeCommuneEtablissement:29019"}
    )
    rows = _fetch(config, tmp_path, monkeypatch, secret="k" * 20)
    assert [r["siret"][-1] for r in rows] == ["1", "2", "3"]
    assert set(keys) == {"k" * 20} and len(keys) == 3


def test_a_cursor_that_comes_back_unchanged_ends_the_paging(tmp_path, monkeypatch):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx2.Response(
            200, json={"next": "same", "items": [{"id": len(calls)}]}
        )

    _serve(monkeypatch, handler)
    config = {
        "url": "https://api.example.gouv.fr/v1",
        "params": {"cursor": "same"},
        "records_path": "$.items",
        "pagination": {"type": "cursor", "cursor_path": "$.next"},
    }
    assert len(_fetch(config, tmp_path, monkeypatch)) == 1


def test_a_preset_caps_an_edited_rate_limit():
    config = preset("sirene-establishments").config({"q": "siren:000000000"})
    config["rate_limit_per_s"] = 50
    assert RestConfig.model_validate(config).rate_limit_per_s == 0.5
    with pytest.raises(ValueError):
        RestConfig.model_validate({**config, "preset": "no-such-preset"})


def test_the_preset_routes_and_sirenes_first_steps(test_db, client_for):
    from server.services.users import create_user

    alice = create_user(test_db, email="alice@test.local", password="pw12345")
    api = client_for(alice, real_credentials=True)
    listed = api.get("/connectors/rest/presets").json()["presets"]
    sirene = next(p for p in listed if p["id"] == "sirene-establishments")
    assert sirene["needs_key"] and sirene["licence"] == "Licence Ouverte 2.0"
    assert api.post("/connectors/rest/presets/nope", json={}).status_code == 404
    bad = api.post("/connectors/rest/presets/geo-communes", json={"departement": "x"})
    assert bad.status_code == 422
    made = api.post(
        "/connectors/rest/presets/sirene-establishments",
        json={"q": "codeCommuneEtablissement:29019"},
    ).json()
    assert made["config"]["auth"] == {
        "type": "header",
        "name": "X-INSEE-Api-Key-Integration",
    }
    source = api.post(
        "/data-sources",
        json={
            "name": made["name"],
            "connector": "rest",
            "config": made["config"],
            "licence": made["licence"],
        },
    ).json()
    recipe = api.post(
        "/recipes",
        json={
            "name": "Sirene",
            "data_source_id": source["id"],
            "target_repo": "alice/sirene",
        },
    ).json()
    dropped = {s["column"] for s in recipe["steps"] if s["method"] == "drop"}
    assert "uniteLegale.nomUniteLegale" in dropped
    assert "uniteLegale.dateNaissanceUniteLegale" in dropped
