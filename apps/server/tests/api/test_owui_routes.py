import pytest
import asyncio
import os
from api.owui import health_check
from api import owui


def test_health_check_returns_parsed_json(monkeypatch):
    class DummyResponse:
        def __init__(self, data):
            self._data = data

        def json(self):
            return self._data

    class DummyAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url):
            return DummyResponse({"status": "ok"})

    monkeypatch.setattr(owui.httpx, "AsyncClient", DummyAsyncClient)
    result = asyncio.run(health_check())
    assert result == {"status": "ok"}


def test_health_check_builds_url_using_owui_url(monkeypatch: pytest.MonkeyPatch):
    class DummyResponse:
        def __init__(self, data):
            self._data = data

        def json(self):
            return self._data

    class DummyAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url):
            # return the received url so the test can assert it was built correctly
            return DummyResponse({"url": url})

    # override module-level OWUI_URL and AsyncClient
    monkeypatch.setattr(owui, "OWUI_URL", "http://example.local")
    monkeypatch.setattr(owui.httpx, "AsyncClient", DummyAsyncClient)

    result = asyncio.run(health_check())
    assert result["url"] == "http://example.local/health"


@pytest.mark.integration
@pytest.mark.skipif(
    reason="Requires actual OWUI service to be reachable",
    condition=not os.getenv("OWUI_URL"),
)
def test_health_check_integration():
    # This test assumes the actual OWUI service is reachable at the default URL
    result = asyncio.run(health_check())
    assert (
        "status" in result
    )  # assuming the real service returns a JSON with a "status" key
