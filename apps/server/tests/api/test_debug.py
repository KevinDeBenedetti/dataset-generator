"""Tests for the dev-only log streaming endpoint (``/debug/logs``).

Neither half of this router is reachable from the shared ``client`` fixture,
which builds its own app and never mounts it — hence a dedicated module.

Two things matter here:

* **The mount must stay gated.** ``main.py`` includes this router *without* the
  ``Depends(get_current_user)`` gate every feature router carries, so the only
  thing standing between a deployment and an unauthenticated stream of raw
  server logs (tokens, request bodies, connection strings) is the ``DEBUG_LOGS``
  check. That check is asserted against the real ``server.main`` module rather
  than a rebuilt stand-in, because a stand-in could not catch the mount moving
  out from behind the flag.
* **The stream itself must behave**: replay the backlog to a late client, emit
  keep-alives while idle, deliver live lines, and unsubscribe on disconnect.
"""

import asyncio
import importlib
import json
from collections.abc import AsyncGenerator
from contextlib import contextmanager
from typing import cast
from unittest.mock import patch

import pytest
from fastapi.responses import StreamingResponse

from server.api import debug as debug_api
from server.core.config import Config, config
from server.core.log_stream import LogBroadcaster


# --------------------------------------------------------------------------
# Mount gating
# --------------------------------------------------------------------------


@contextmanager
def _main_with_debug_logs(enabled: bool):
    """Re-import ``server.main`` with ``config.debug_logs`` forced to ``enabled``.

    The flag is read once, at import time, so the mount can only be re-evaluated
    by reloading ``server.main``. The *attribute* is patched rather than the
    environment: rebuilding ``server.core.config`` would swap the ``config``
    singleton for a new object while every module that did
    ``from server.core.config import config`` keeps the original, so later tests
    patching the singleton would silently stop reaching the code under test.
    (Env-to-flag parsing is covered separately, against ``Config`` directly.)

    Langfuse availability is stubbed because importing main otherwise performs a
    real ``auth_check`` round-trip.
    """

    def _reload_main():
        with patch(
            "server.services.langfuse.is_langfuse_available", return_value=False
        ):
            return importlib.reload(importlib.import_module("server.main"))

    try:
        with patch.object(config, "debug_logs", enabled):
            yield _reload_main()
    finally:
        # Leave the module holding an app built from the real flag again.
        _reload_main()


def _route_paths(main_module) -> set[str]:
    """Paths the app actually exposes.

    Read from the generated schema rather than ``app.routes``: included routers
    stay nested (``_IncludedRouter``) instead of being flattened, so scanning
    ``.path`` at the top level silently reports every router as absent — which
    would make the "not mounted" assertion below pass no matter what.
    """
    return set(main_module.app.openapi()["paths"])


def test_debug_router_is_not_mounted_when_the_flag_is_off():
    """The security-relevant case: flag off means the route does not exist."""
    with _main_with_debug_logs(False) as main_module:
        paths = _route_paths(main_module)

    assert "/debug/logs" not in paths
    assert not [p for p in paths if p.startswith("/debug")]


def test_debug_router_is_mounted_when_the_flag_is_on():
    with _main_with_debug_logs(True) as main_module:
        paths = _route_paths(main_module)

    assert "/debug/logs" in paths


def test_health_route_is_unaffected_by_the_debug_flag():
    """Guards the reload helper itself: the rest of the app must still be there."""
    with _main_with_debug_logs(False) as main_module:
        paths = _route_paths(main_module)

    assert {"/health", "/"} <= paths


@pytest.mark.parametrize("value", ["", "false", "False", "0", "no", "  "])
def test_falsy_env_values_leave_the_flag_off(monkeypatch, value):
    """A blank value matters on its own — `.env.example` ships keys with no
    value and `make env` copies it verbatim, so ``DEBUG_LOGS=`` reaches the app
    and must not read as "enabled"."""
    monkeypatch.setenv("DEBUG_LOGS", value)

    assert Config().debug_logs is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_truthy_env_values_turn_the_flag_on(monkeypatch, value):
    monkeypatch.setenv("DEBUG_LOGS", value)

    assert Config().debug_logs is True


def test_flag_is_off_when_the_variable_is_absent(monkeypatch):
    monkeypatch.delenv("DEBUG_LOGS", raising=False)

    assert Config().debug_logs is False


# --------------------------------------------------------------------------
# Stream behaviour
# --------------------------------------------------------------------------


@pytest.fixture
def broadcaster(monkeypatch) -> LogBroadcaster:
    """An isolated broadcaster so a test doesn't stream the whole suite's logs.

    The keep-alive interval is shortened at the same time: the generator spends
    its idle time inside ``wait_for(queue.get(), _KEEPALIVE_INTERVAL)``, and the
    production 15s would make every idle assertion below a 15s wait.
    """
    isolated = LogBroadcaster(capacity=10)
    monkeypatch.setattr(debug_api, "broadcaster", isolated)
    monkeypatch.setattr(debug_api, "_KEEPALIVE_INTERVAL", 0.05)
    return isolated


def _stream_of(response: StreamingResponse) -> AsyncGenerator[str | bytes, None]:
    """The response body as the async *generator* it actually is.

    ``StreamingResponse`` types ``body_iterator`` as ``AsyncIterable``, which
    has no ``aclose()`` — but these tests must close the stream explicitly,
    since the endpoint's generator never ends on its own.
    """
    return cast(AsyncGenerator[str | bytes, None], response.body_iterator)


async def _next_chunk(
    iterator: AsyncGenerator[str | bytes, None], timeout: float = 5.0
) -> str:
    """Pull one SSE chunk, failing the test rather than hanging forever."""
    chunk = await asyncio.wait_for(anext(iterator), timeout)
    return chunk.decode() if isinstance(chunk, bytes) else chunk


def _payload(chunk: str) -> dict:
    assert chunk.startswith("data: ") and chunk.endswith("\n\n")
    return json.loads(chunk[len("data: ") : -2])


# The stream is driven through the response's own async iterator instead of
# ``TestClient``: the generator never completes, and TestClient's sync bridge
# blocks forever on a body that has no end.


def test_format_emits_one_json_sse_event():
    formatted = debug_api._format("INFO | boot")

    assert formatted.endswith("\n\n")
    assert _payload(formatted) == {"source": "fastapi", "line": "INFO | boot"}


async def test_stream_is_declared_as_an_unbuffered_event_stream(broadcaster):
    response = await debug_api.stream_logs()
    try:
        assert response.media_type == "text/event-stream"
        assert response.headers["cache-control"] == "no-cache, no-transform"
        # Without this an nginx in front would hold events back until its buffer
        # fills, which for a log trickle means the console looks frozen.
        assert response.headers["x-accel-buffering"] == "no"
    finally:
        await _stream_of(response).aclose()


async def test_stream_replays_the_backlog_to_a_late_client(broadcaster):
    """A client connecting after the fact still gets recent context."""
    broadcaster.emit("older line")
    broadcaster.emit("newer line")

    response = await debug_api.stream_logs()
    iterator = _stream_of(response)
    try:
        first = _payload(await _next_chunk(iterator))
        second = _payload(await _next_chunk(iterator))
    finally:
        await iterator.aclose()

    assert [first["line"], second["line"]] == ["older line", "newer line"]
    assert first["source"] == "fastapi"


async def test_stream_sends_keepalives_while_idle(broadcaster):
    """Silence must produce comment lines, not a stream an idle proxy drops."""
    response = await debug_api.stream_logs()
    iterator = _stream_of(response)
    try:
        assert await _next_chunk(iterator) == ": keep-alive\n\n"
        assert await _next_chunk(iterator) == ": keep-alive\n\n"
    finally:
        await iterator.aclose()


async def test_stream_delivers_lines_emitted_after_the_client_connected(broadcaster):
    """The live path — the backlog replay above can't exercise the queue."""
    response = await debug_api.stream_logs()
    iterator = _stream_of(response)
    try:
        # One keep-alive first: it proves the empty backlog is drained and the
        # generator is parked on the queue, so the emit below can't be missed.
        assert await _next_chunk(iterator) == ": keep-alive\n\n"

        broadcaster.emit("live line")

        assert _payload(await _next_chunk(iterator))["line"] == "live line"
    finally:
        await iterator.aclose()


async def test_stream_unsubscribes_when_the_client_goes_away(broadcaster):
    """Otherwise every reconnect leaks a queue that is fed for the process' life."""
    response = await debug_api.stream_logs()
    iterator = _stream_of(response)

    assert await _next_chunk(iterator) == ": keep-alive\n\n"
    assert len(broadcaster._subscribers) == 1

    await iterator.aclose()

    assert broadcaster._subscribers == set()
