"""In-memory log broadcaster for the dev log console.

A logging handler ([`BroadcastLogHandler`][]) fans every formatted log record out
to two places:

* a bounded ring buffer (so a client that connects late still sees recent lines), and
* a set of per-subscriber :class:`asyncio.Queue` instances consumed by the
  ``/debug/logs`` SSE endpoint.

Records can be emitted from worker threads (e.g. ``asyncio.to_thread``), so live
delivery hops onto the bound event loop via ``call_soon_threadsafe``. The ring
buffer itself is a :class:`collections.deque`, whose ``append`` is atomic under
the GIL, so buffering works even before any event loop is bound.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Deque, Set


class LogBroadcaster:
    """Buffers recent log lines and pushes new ones to live SSE subscribers."""

    def __init__(self, capacity: int = 500) -> None:
        self._buffer: Deque[str] = deque(maxlen=capacity)
        self._subscribers: Set[asyncio.Queue[str]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Remember the event loop used to deliver lines to subscribers."""
        self._loop = loop

    def emit(self, message: str) -> None:
        """Buffer ``message`` and deliver it to every live subscriber."""
        self._buffer.append(message)
        loop = self._loop
        if loop is None:
            return
        for queue in list(self._subscribers):
            try:
                loop.call_soon_threadsafe(_safe_put, queue, message)
            except RuntimeError:
                # Loop is closed/stopped — drop the line rather than crash logging.
                pass

    def subscribe(self) -> "asyncio.Queue[str]":
        """Register a new subscriber and return its queue."""
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1000)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: "asyncio.Queue[str]") -> None:
        """Remove a subscriber (safe to call more than once)."""
        self._subscribers.discard(queue)

    def snapshot(self) -> list[str]:
        """Return the buffered backlog, oldest first."""
        return list(self._buffer)


def _safe_put(queue: "asyncio.Queue[str]", message: str) -> None:
    """Enqueue without raising: a slow client that fills its queue drops lines."""
    try:
        queue.put_nowait(message)
    except asyncio.QueueFull:
        pass


# Process-wide singleton shared by the logging handler and the SSE endpoint.
broadcaster = LogBroadcaster()


class BroadcastLogHandler(logging.Handler):
    """A logging handler that forwards formatted records to the broadcaster."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
        except Exception:  # pragma: no cover - never let logging crash the app
            return
        broadcaster.emit(message)
