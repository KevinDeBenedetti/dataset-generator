"""Tests for the dev log console broadcaster."""

import asyncio
import logging

import pytest

from server.core.log_stream import (
    BroadcastLogHandler,
    LogBroadcaster,
    _safe_put,
)


class TestLogBroadcaster:
    def test_snapshot_returns_buffered_lines_oldest_first(self):
        b = LogBroadcaster(capacity=10)
        b.emit("first")
        b.emit("second")
        assert b.snapshot() == ["first", "second"]

    def test_buffer_is_bounded_to_capacity(self):
        b = LogBroadcaster(capacity=3)
        for i in range(5):
            b.emit(f"line-{i}")
        # Only the most recent `capacity` lines are kept.
        assert b.snapshot() == ["line-2", "line-3", "line-4"]

    def test_emit_without_bound_loop_does_not_raise(self):
        b = LogBroadcaster()
        # No loop bound yet — buffering still works, delivery is skipped.
        b.emit("orphan")
        assert b.snapshot() == ["orphan"]

    @pytest.mark.asyncio
    async def test_emit_delivers_to_live_subscriber(self):
        b = LogBroadcaster()
        b.bind_loop(asyncio.get_running_loop())
        queue = b.subscribe()

        b.emit("hello")
        # Delivery is scheduled via call_soon_threadsafe; yield to let it run.
        line = await asyncio.wait_for(queue.get(), timeout=1)
        assert line == "hello"

    @pytest.mark.asyncio
    async def test_unsubscribe_stops_delivery(self):
        b = LogBroadcaster()
        b.bind_loop(asyncio.get_running_loop())
        queue = b.subscribe()
        b.unsubscribe(queue)

        b.emit("ignored")
        await asyncio.sleep(0)
        assert queue.empty()

    def test_safe_put_drops_when_queue_full(self):
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1)
        _safe_put(queue, "a")
        # Second put would raise QueueFull; _safe_put swallows it.
        _safe_put(queue, "b")
        assert queue.qsize() == 1


class TestBroadcastLogHandler:
    def test_handler_forwards_formatted_record(self):
        b = LogBroadcaster()
        handler = BroadcastLogHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:%(message)s"))

        # Point the handler's emit at our isolated broadcaster.
        import server.core.log_stream as mod

        original = mod.broadcaster
        mod.broadcaster = b
        try:
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname=__file__,
                lineno=1,
                msg="hi %s",
                args=("there",),
                exc_info=None,
            )
            handler.emit(record)
        finally:
            mod.broadcaster = original

        assert b.snapshot() == ["INFO:hi there"]
