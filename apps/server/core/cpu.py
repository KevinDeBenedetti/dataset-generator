"""The executor for heavy blocking work: dedup passes, HTML stripping, and the
embedding batches sent to the endpoint.

Off the default thread pool on purpose. The worker's heartbeats, the API's
database calls and every other short blocking call share that pool, and a few
large uploads' worth of embedding batches would queue them behind minutes of
work — long enough for ``services.queue.reap_stale`` to take a live run for
a dead one. ``EMBEDDED_WORKER`` (``make dev-local``), where the API and the
worker share one process, suffers first. The pool is also bounded to the cores,
so the work doesn't oversubscribe them.
"""

import asyncio
import contextvars
import functools
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, TypeVar

T = TypeVar("T")

CPU_THREADS = max(1, (os.cpu_count() or 2) // 2)
_EXECUTOR = ThreadPoolExecutor(max_workers=CPU_THREADS, thread_name_prefix="cpu")


async def cpu_bound(fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Run ``fn(*args, **kwargs)`` on the CPU executor — ``asyncio.to_thread``,
    on this pool instead of the default one (the context is carried over too)."""
    loop = asyncio.get_running_loop()
    context = contextvars.copy_context()
    call = functools.partial(context.run, fn, *args, **kwargs)
    return await loop.run_in_executor(_EXECUTOR, call)
