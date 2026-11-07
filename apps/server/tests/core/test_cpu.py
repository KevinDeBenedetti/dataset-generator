"""The CPU executor (core/cpu.py): its own threads, off the default pool."""

import asyncio
import threading
import time

import pytest

from server.core import cpu


async def test_runs_on_a_cpu_thread_and_returns_the_value():
    seen = {}

    def work(a, *, b):
        seen["thread"] = threading.current_thread().name
        return a + b

    assert await cpu.cpu_bound(work, 1, b=2) == 3
    assert seen["thread"].startswith("cpu")
    assert seen["thread"] != threading.main_thread().name


async def test_an_exception_comes_back():
    def boom():
        raise ValueError("no")

    with pytest.raises(ValueError, match="no"):
        await cpu.cpu_bound(boom)


async def test_cpu_work_does_not_delay_the_default_pool():
    """What the executor is for: with every CPU thread busy (and more work
    queued), a short call on the default pool — a worker's heartbeat — still
    answers at once instead of waiting its turn behind the CPU work."""
    busy = [
        asyncio.create_task(cpu.cpu_bound(time.sleep, 0.3))
        for _ in range(cpu.CPU_THREADS + 2)
    ]
    await asyncio.sleep(0.05)  # the CPU threads are all sleeping by now

    t = time.perf_counter()
    await asyncio.to_thread(lambda: None)  # the heartbeat's kind of call
    assert time.perf_counter() - t < 0.1

    await asyncio.gather(*busy)
