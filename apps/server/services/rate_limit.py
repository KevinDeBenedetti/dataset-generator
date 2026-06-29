"""Sliding-window rate limiting for the login endpoint.

Used to throttle brute-force login attempts. Two backends share one interface:

- :class:`SlidingWindowRateLimiter` keeps state in this process only, so it is
  NOT shared across uvicorn workers or replicas — a first defensive layer.
- :class:`RedisSlidingWindowRateLimiter` keeps the same window in a Redis sorted
  set, so the quota is shared across all workers/replicas.

The module-level ``login_rate_limiter`` picks the Redis backend when
``config.redis_url`` is set and reachable, falling back to the in-process one
otherwise (an unset/unreachable Redis must not break logins).
"""

import logging
import threading
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, Optional, Protocol


class RateLimiter(Protocol):
    """The interface the login route depends on (both backends satisfy it)."""

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


class RedisSlidingWindowRateLimiter:
    """Redis-backed sliding window, shared across workers/replicas.

    Each key maps to a Redis sorted set whose members are individual failed
    attempts scored by wall-clock time. Stale members are pruned by score on
    read, and the set is given a TTL so idle keys expire on their own.

    Uses wall-clock ``time.time()`` (not monotonic) so timestamps are comparable
    across processes. The ``client`` is injectable for testing.
    """

    def __init__(
        self,
        max_attempts: int,
        window_seconds: float,
        client: Any,
        key_prefix: str = "ratelimit:login:",
    ):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._client = client
        self._key_prefix = key_prefix

    def _rkey(self, key: str) -> str:
        return f"{self._key_prefix}{key}"

    def retry_after(self, key: str) -> float:
        now = time.time()
        rkey = self._rkey(key)
        self._client.zremrangebyscore(rkey, 0, now - self.window_seconds)
        count = self._client.zcard(rkey)
        if count >= self.max_attempts:
            oldest = self._client.zrange(rkey, 0, 0, withscores=True)
            if oldest:
                oldest_score = oldest[0][1]
                return max(0.0, oldest_score + self.window_seconds - now)
        return 0.0

    def register_failure(self, key: str) -> None:
        now = time.time()
        rkey = self._rkey(key)
        # Unique member per attempt (ns timestamp) so concurrent failures at the
        # same second don't collide into one sorted-set entry.
        self._client.zadd(rkey, {str(time.time_ns()): now})
        # Refresh the TTL so an idle key is reclaimed a full window after its
        # last failure (ceil so a sub-second window still gets >=1s).
        self._client.expire(rkey, int(self.window_seconds) + 1)

    def reset(self, key: str) -> None:
        self._client.delete(self._rkey(key))

    def clear(self) -> None:
        """Drop all keys under the prefix (mainly for test isolation)."""
        for rkey in self._client.scan_iter(match=f"{self._key_prefix}*"):
            self._client.delete(rkey)


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

        client = redis.Redis.from_url(config.redis_url, decode_responses=True)
        client.ping()
    except Exception as exc:  # noqa: BLE001 — degrade gracefully, never crash
        logging.warning(
            "Redis unavailable for login rate limiting (%s) — falling back to "
            "in-process limiter.",
            exc,
        )
        return in_process

    logging.info("Login rate limiter backed by Redis at %s", config.redis_url)
    return RedisSlidingWindowRateLimiter(
        max_attempts=config.auth_login_max_attempts,
        window_seconds=config.auth_login_window_seconds,
        client=client,
    )


# Process-wide limiter for the login endpoint.
login_rate_limiter: RateLimiter = _build_login_limiter()
