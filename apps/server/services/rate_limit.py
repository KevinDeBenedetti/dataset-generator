"""Rate limiting for the login endpoint.

Used to throttle brute-force login attempts. Two backends share one interface:

- :class:`SlidingWindowRateLimiter` keeps state in this process only, so it is
  NOT shared across uvicorn workers or replicas — a first defensive layer.
- :class:`RedisRateLimiter` delegates to ``redis-fastapi``'s ``RateLimitBackend``
  (Redis' own FastAPI SDK), so the quota is shared across all workers/replicas
  and each attempt is counted **atomically** (INCREX on Redis 8.8+, an atomic
  Lua script below that). The previous hand-rolled sorted-set backend read and
  wrote in separate round trips, so concurrent attempts could both observe a
  count under the cap and slip past it.

The trade-off of that move: the Redis backend is now a **fixed** window (a
counter with a TTL) rather than a sliding one. The window starts at the first
counted failure and does not extend as more arrive; the in-process backend still
slides. For an anti-brute-force throttle the difference is a boundary effect, not
a hole — the cap per window is unchanged.

The SDK reads its own settings from ``REDIS_*`` env vars: the key namespace
(``REDIS_PREFIX``, default ``redis:fastapi``) and ``REDIS_RATE_LIMIT_FAIL_CLOSED``
(default false). Leave the latter false — a Redis outage must cost throttling,
not logins; :meth:`RedisRateLimiter._guard` enforces the same rule for anything
the SDK doesn't catch.

The module-level ``login_rate_limiter`` picks the Redis backend when
``config.redis_url`` is set and reachable, falling back to the in-process one
otherwise (an unset/unreachable Redis must not break logins). That guarantee
also holds once the backend is chosen: a Redis that goes away later degrades to
"no throttling" rather than failing the login (see ``_guard``).
"""

import logging
import math
import threading
import time
from collections import defaultdict, deque
from typing import Any, Callable, Deque, Dict, Optional, Protocol


class RateLimiter(Protocol):
    """The interface the login route depends on (both backends satisfy it)."""

    # Tunable cap both backends expose (read in their methods, adjustable in tests).
    max_attempts: int

    def retry_after(self, key: str) -> float: ...

    def register_failure(self, key: str) -> None: ...

    def reset(self, key: str) -> None: ...

    def clear(self) -> None: ...


class SlidingWindowRateLimiter:
    """Track event timestamps per key and block once a key exceeds the cap.

    ``max_attempts`` events are allowed within any ``window_seconds`` window.
    Only failures are typically recorded (success calls :meth:`reset`), so a
    legitimate login never counts against the limit.
    """

    def __init__(self, max_attempts: int, window_seconds: float):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._events: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> None:
        events = self._events.get(key)
        if events is None:
            return
        cutoff = now - self.window_seconds
        while events and events[0] <= cutoff:
            events.popleft()
        if not events:
            self._events.pop(key, None)

    def retry_after(self, key: str, now: Optional[float] = None) -> float:
        """Seconds until the next attempt is allowed; 0.0 when not blocked."""
        now = time.monotonic() if now is None else now
        with self._lock:
            self._prune(key, now)
            events = self._events.get(key)
            if events and len(events) >= self.max_attempts:
                return max(0.0, events[0] + self.window_seconds - now)
            return 0.0

    def register_failure(self, key: str, now: Optional[float] = None) -> None:
        """Record one failed attempt for ``key``."""
        now = time.monotonic() if now is None else now
        with self._lock:
            self._events[key].append(now)

    def reset(self, key: str) -> None:
        """Forget a key's history (e.g. after a successful login)."""
        with self._lock:
            self._events.pop(key, None)

    def clear(self) -> None:
        """Drop all tracked keys (mainly for test isolation)."""
        with self._lock:
            self._events.clear()


class RedisRateLimiter:
    """Login throttling on ``redis-fastapi``'s ``RateLimitBackend``.

    The SDK owns the counting: one Redis key per identifier, incremented
    atomically (``INCREX``, or an atomic Lua script on servers without it) and
    expiring on its own after the window. That atomicity is the reason this
    replaced the hand-rolled sorted-set backend.

    Two adaptations sit here rather than in the SDK:

    * **Only failures are counted.** The SDK's ``hit`` is called from
      :meth:`register_failure`, never on the way in; :meth:`retry_after` uses
      ``peek``, which reads the counter without consuming from it. A legitimate
      login therefore never spends quota, and a successful one clears the key.
    * **Nothing may break the login.** The SDK already fails open on Redis
      errors (``REDIS_RATE_LIMIT_FAIL_CLOSED`` defaults to false), but that only
      covers ``RedisError``/``OSError``. :meth:`_guard` widens it to anything —
      including the "not in a worker thread" case below — so a degraded Redis
      costs throttling, never availability.

    ``backend`` is the SDK's **async** ``RateLimitBackend``; its coroutines are
    driven from this sync API via ``anyio.from_thread.run``, which requires a
    FastAPI worker thread — what a sync ``def`` endpoint runs in (see
    ``api/auth.py:login``). Turning that route into ``async def`` would move it
    onto the event-loop thread, where the bridge raises and this limiter would
    degrade to "no throttling" (loudly, one warning per call).
    """

    def __init__(
        self,
        max_attempts: int,
        window_seconds: float,
        backend: Any,
        client: Any = None,
        key_prefix: str = "",
    ):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        # The SDK counts in whole seconds; never round a sub-second window to 0.
        self._window = max(1, math.ceil(window_seconds))
        self._backend = backend
        # Only :meth:`clear` needs the raw client (the SDK has no "drop every
        # key in this scope" operation).
        self._client = client
        self._key_prefix = key_prefix

    @staticmethod
    def _run_async(factory: Callable[[], Any]) -> Any:
        """Await an SDK coroutine from this synchronous API."""
        import anyio.from_thread

        return anyio.from_thread.run(factory)

    def _guard(self, action: str, factory: Callable[[], Any], default=None):
        """Run an async backend call, degrading to ``default`` on any failure.

        The backend is chosen once at startup, so a Redis that dies *afterwards*
        would otherwise raise straight through :func:`login` and turn every
        attempt into a 500. Rate limiting is a defensive layer, not an
        authentication check: losing it must not lock everyone out. Failures are
        logged so a persistently unreachable Redis stays visible.
        """
        try:
            return self._run_async(factory)
        except Exception as exc:  # noqa: BLE001 — degrade gracefully, never crash
            logging.warning(
                "Redis unavailable for login rate limiting during %s (%s) — "
                "allowing the attempt; brute-force throttling is degraded.",
                action,
                exc,
            )
            return default

    def retry_after(self, key: str) -> float:
        """Seconds until the next attempt is allowed; 0.0 when not blocked."""
        result = self._guard(
            "retry_after",
            lambda: self._backend.peek(
                key, limit=self.max_attempts, window=self._window
            ),
        )
        # No result (backend error) or under the cap → let the attempt through.
        # A degraded result carries the fail-open verdict the SDK already made.
        if result is None or result.allowed:
            return 0.0
        return float(result.retry_after)

    def register_failure(self, key: str) -> None:
        """Count one failed attempt for ``key``."""
        self._guard(
            "register_failure",
            lambda: self._backend.hit(
                key, limit=self.max_attempts, window=self._window
            ),
        )

    def reset(self, key: str) -> None:
        """Forget a key's counter (e.g. after a successful login)."""
        self._guard("reset", lambda: self._backend.reset(key))

    def clear(self) -> None:
        """Drop every key in this limiter's scope (mainly for test isolation)."""
        if self._client is None:
            return

        async def _run() -> None:
            async for rkey in self._client.scan_iter(match=f"{self._key_prefix}*"):
                await self._client.delete(rkey)

        self._guard("clear", _run)


# Scope segment the SDK puts between its global prefix and the identifier, so
# the login counters sit in their own namespace (redis:fastapi:ratelimit:login:*).
LOGIN_SCOPE = "login"


def _build_login_limiter() -> RateLimiter:
    """Pick the Redis backend when configured/reachable, else in-process.

    A misconfigured or unreachable Redis must never break logins, so any failure
    building/pinging the client downgrades to the in-process limiter.
    """
    from server.core.config import config

    in_process = SlidingWindowRateLimiter(
        max_attempts=config.auth_login_max_attempts,
        window_seconds=config.auth_login_window_seconds,
    )
    if not config.redis_url:
        return in_process

    try:
        import redis

        # Reachability probe only: the SDK backend needs an *async* client, and
        # awaiting a ping at import time would bind its pool to a throwaway
        # event loop. This sync client is closed immediately; an unreachable
        # Redis at startup still means the in-process limiter, as before.
        probe = redis.Redis.from_url(config.redis_url)
        probe.ping()
        probe.close()

        from redis.asyncio import Redis as AsyncRedis
        from redis_fastapi import RateLimitBackend
        from redis_fastapi.config import get_settings

        client = AsyncRedis.from_url(config.redis_url, decode_responses=True)
        backend = RateLimitBackend(client, scope=LOGIN_SCOPE)
        key_prefix = f"{get_settings().pattern_prefix('ratelimit')}:{LOGIN_SCOPE}:"
    except Exception as exc:  # noqa: BLE001 — degrade gracefully, never crash
        logging.warning(
            "Redis unavailable for login rate limiting (%s) — falling back to "
            "in-process limiter.",
            exc,
        )
        return in_process

    logging.info("Login rate limiter backed by Redis at %s", config.redis_url)
    return RedisRateLimiter(
        max_attempts=config.auth_login_max_attempts,
        window_seconds=config.auth_login_window_seconds,
        backend=backend,
        client=client,
        key_prefix=key_prefix,
    )


# Process-wide limiter for the login endpoint.
login_rate_limiter: RateLimiter = _build_login_limiter()
