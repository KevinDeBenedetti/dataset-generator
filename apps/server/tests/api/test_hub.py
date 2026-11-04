"""The Hub viewer routes (api/hub.py): parameters in, service errors out.

The service is stubbed: what matters here is how each route calls it and how
its errors become HTTP answers (services/hub.py has its own tests). No database
is involved, so the app is just the hub router with the caller's credentials.
"""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api import hub as hub_api
from server.api.deps import get_credentials
from server.services import hub
from server.services.huggingface import HuggingFaceNotConfiguredError
from server.tests.creds import make_creds

CREDS = make_creds(hf_token="hf_test_token")

ROWS = {
    "repo_id": "kevin/qa",
    "sha": "a" * 40,
    "config": "default",
    "split": "train",
    "features": [{"name": "question", "type": "string", "kind": "string"}],
    "qa": None,
    "rows": [{"row_idx": 0, "row": {"question": "Q?"}, "truncated_cells": []}],
    "num_rows_total": 1,
    "num_rows_matched": 1,
    "offset": 0,
    "length": 25,
}


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(hub_api.router)
    app.dependency_overrides[get_credentials] = lambda: CREDS
    return TestClient(app)


def test_rows_pass_the_query_through(client):
    with patch.object(hub, "rows", return_value=ROWS) as rows:
        response = client.get(
            "/hub/datasets/kevin/qa/rows",
            params={
                "config": "default",
                "split": "train",
                "revision": "v1",
                "offset": 50,
                "length": 50,
                "q": "alpha",
                "filters": '[{"column": "category", "op": "eq", "value": "docs"}]',
                "sort": "confidence",
                "order": "desc",
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["rows"][0]["row"] == {"question": "Q?"}
    args, kwargs = rows.call_args
    assert args == (CREDS, "kevin/qa")
    assert kwargs == {
        "revision": "v1",
        "config_name": "default",
        "split": "train",
        "offset": 50,
        "length": 50,
        "query": "alpha",
        "filters": [hub.RowFilter("category", "eq", "docs")],
        "sort": "confidence",
        "order": "desc",
    }


@pytest.mark.parametrize(
    "filters",
    [
        "not json",
        '{"column": "x"}',
        '[{"column": "x", "op": "matches", "value": "y"}]',
        '[{"op": "eq", "value": "y"}]',
    ],
)
def test_malformed_filters_are_a_400(client, filters):
    with patch.object(hub, "rows") as rows:
        response = client.get(
            "/hub/datasets/kevin/qa/rows", params={"filters": filters}
        )

    assert response.status_code == 400
    rows.assert_not_called()


def test_page_length_is_bounded(client):
    response = client.get("/hub/datasets/kevin/qa/rows", params={"length": 101})
    assert response.status_code == 422


def test_an_implausible_repo_id_is_a_404(client):
    with patch.object(hub, "overview") as overview:
        response = client.get("/hub/datasets/kevin/..hidden")

    assert response.status_code == 404
    overview.assert_not_called()


@pytest.mark.parametrize(
    "error,status",
    [
        (HuggingFaceNotConfiguredError("Add your Hugging Face token in Settings"), 503),
        (hub.HubNotFoundError("Dataset not found"), 404),
        (hub.HubTooLargeError("Too large"), 413),
        (hub.HubBadQueryError("Unknown column 'x'"), 400),
        (hub.HubUnreadableError("'a.jsonl' could not be read as a table"), 422),
    ],
)
def test_service_errors_map_to_http(client, error, status):
    with patch.object(hub, "statistics", side_effect=error):
        response = client.get("/hub/datasets/kevin/qa/statistics")

    assert response.status_code == status
    assert response.json()["detail"] == str(error)


@pytest.mark.parametrize(
    "error",
    [
        hub.HubUnavailableError("https://hub.internal/req-123 failed"),
        RuntimeError("secret internals"),
    ],
)
def test_hub_failures_do_not_leak_internals(client, error):
    with patch.object(hub, "commits", side_effect=error):
        response = client.get("/hub/datasets/kevin/qa/commits")

    assert response.status_code == 502
    assert "internal" not in response.text and "secret" not in response.text


def test_listing_takes_a_namespace(client):
    listing = {
        "namespace": "kevin-org",
        "namespaces": ["kevin", "kevin-org"],
        "total": 0,
        "datasets": [],
    }
    with patch.object(hub, "list_datasets", return_value=listing) as list_datasets:
        response = client.get("/hub/datasets", params={"author": "kevin-org"})

    assert response.status_code == 200
    assert response.json() == listing
    list_datasets.assert_called_once_with(CREDS, "kevin-org")


def test_compare_needs_a_base(client):
    assert client.get("/hub/datasets/kevin/qa/compare").status_code == 422


def test_row_needs_a_position(client):
    assert client.get("/hub/datasets/kevin/qa/row").status_code == 422
    assert (
        client.get("/hub/datasets/kevin/qa/row", params={"row_idx": -1}).status_code
        == 422
    )
