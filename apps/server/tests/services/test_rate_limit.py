"""Unit tests for the login rate limiters (in-process and Redis-backed)."""

from server.services.rate_limit import (
    RedisRateLimiter,
    SlidingWindowRateLimiter,
)


def test_allows_up_to_max_then_blocks():
    limiter = SlidingWindowRateLimiter(max_attempts=3, window_seconds=60)
    # A controlled clock so the test is deterministic.
    t = 1000.0

    # First 3 failures are allowed (not blocked between them).
    for _ in range(3):
        assert limiter.retry_after("ip", now=t) == 0.0
        limiter.register_failure("ip", now=t)

    # The 4th check is blocked, with a Retry-After up to the window length.
    blocked = limiter.retry_after("ip", now=t)
    assert blocked > 0
    assert blocked <= 60


def test_window_slides_and_unblocks():
    limiter = SlidingWindowRateLimiter(max_attempts=2, window_seconds=60)
    limiter.register_failure("ip", now=0.0)
    limiter.register_failure("ip", now=10.0)
    assert limiter.retry_after("ip", now=10.0) > 0  # blocked

    # After the oldest failure ages out of the window, the key is allowed again.
    assert limiter.retry_after("ip", now=61.0) == 0.0


def test_reset_clears_a_key():
    limiter = SlidingWindowRateLimiter(max_attempts=1, window_seconds=60)
    limiter.register_failure("ip", now=0.0)
    assert limiter.retry_after("ip", now=0.0) > 0

    limiter.reset("ip")
    assert limiter.retry_after("ip", now=0.0) == 0.0


def test_keys_are_independent():
    limiter = SlidingWindowRateLimiter(max_attempts=1, window_seconds=60)
    limiter.register_failure("a", now=0.0)
    assert limiter.retry_after("a", now=0.0) > 0
    # A different IP is unaffected.
    assert limiter.retry_after("b", now=0.0) == 0.0


# --- Redis-backed limiter (redis-fastapi SDK) --------------------------------
#
# `RedisRateLimiter` exposes a sync API over the SDK's async backend, bridged by
# `anyio.from_thread.run` — which only works inside a worker thread owned by a
# running event loop. That is exactly where FastAPI runs a sync `def` endpoint
# (api/auth.py:login), so every test below drives the limiter through
# `anyio.to_thread.run_sync`, reproducing the real call path instead of a
# friendlier one that would hide the constraint.


class FakeAsyncRedis:
    """In-memory stand-in for the async commands the SDK/limiter use."""

    def __init__(self):
        self.values: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, name):
        value = self.values.get(name)
        return None if value is None else str(value)

    async def pttl(self, name):
        # -2 is redis' "no such key"; the SDK reads that as a fresh window.
        return self.ttls.get(name, -2) * 1000 if name in self.ttls else -2

    async def delete(self, name):
        self.ttls.pop(name, None)
        return 1 if self.values.pop(name, None) is not None else 0

    async def scan_iter(self, match=None):
        for key in [k for k in list(self.values) if _matches(k, match)]:
            yield key


def _matches(key, pattern):
    import fnmatch

    return pattern is None or fnmatch.fnmatch(key, pattern)


class FakeBackend:
    """The window-counter contract the limiter relies on, without Redis.

    Mirrors `RateLimitBackend`: `hit` consumes (and refuses to go past the
    limit), `peek` only reads, `reset` drops the key.
    """

    def __init__(self, client: FakeAsyncRedis, scope: str = "login"):
        self.client = client
        self.scope = scope

    def _key(self, identifier):
        return f"redis:fastapi:ratelimit:{self.scope}:{identifier}"

    async def hit(self, identifier, *, limit, window, **_kwargs):
        key = self._key(identifier)
        current = self.client.values.get(key, 0)
        allowed = current + 1 <= limit
        if allowed:
            self.client.values[key] = current + 1
            self.client.ttls[key] = window
        return _Result(allowed=allowed, retry_after=window)

    async def peek(self, identifier, *, limit, window, **_kwargs):
        key = self._key(identifier)
        current = self.client.values.get(key, 0)
        return _Result(allowed=current < limit, retry_after=window)

    async def reset(self, identifier, **_kwargs):
        return bool(await self.client.delete(self._key(identifier)))


class _Result:
    """Just the two `RateLimitResult` fields the limiter reads."""

    def __init__(self, *, allowed: bool, retry_after: int):
        self.allowed = allowed
        self.retry_after = retry_after


def _limiter(max_attempts=2, window_seconds=60, backend=None, client=None):
    client = client if client is not None else FakeAsyncRedis()
    return RedisRateLimiter(
        max_attempts=max_attempts,
        window_seconds=window_seconds,
        backend=backend if backend is not None else FakeBackend(client),
        client=client,
        key_prefix="redis:fastapi:ratelimit:login:",
    )


async def _in_worker_thread(fn, *args):
    """Run `fn` where FastAPI runs a sync endpoint: an anyio worker thread."""
    import anyio.to_thread

    return await anyio.to_thread.run_sync(lambda: fn(*args))


async def test_redis_blocks_after_max():
    limiter = _limiter(max_attempts=2)

    def _scenario():
        first = limiter.retry_after("ip")
        limiter.register_failure("ip")
        limiter.register_failure("ip")
        return first, limiter.retry_after("ip")

    first, blocked = await _in_worker_thread(_scenario)
    assert first == 0.0
    assert blocked > 0
    assert blocked <= 60


async def test_checking_does_not_consume_quota():
    """Only failures count: peeking must never spend an attempt."""
    limiter = _limiter(max_attempts=1)

    def _scenario():
        for _ in range(5):
            limiter.retry_after("ip")
        return limiter.retry_after("ip")

    assert await _in_worker_thread(_scenario) == 0.0


async def test_redis_reset_clears_a_key():
    limiter = _limiter(max_attempts=1)

    def _scenario():
        limiter.register_failure("ip")
        blocked = limiter.retry_after("ip")
        limiter.reset("ip")
        return blocked, limiter.retry_after("ip")

    blocked, after_reset = await _in_worker_thread(_scenario)
    assert blocked > 0
    assert after_reset == 0.0


async def test_redis_keys_are_independent():
    limiter = _limiter(max_attempts=1)

    def _scenario():
        limiter.register_failure("a")
        return limiter.retry_after("a"), limiter.retry_after("b")

    blocked_a, other = await _in_worker_thread(_scenario)
    assert blocked_a > 0
    assert other == 0.0


async def test_redis_clear_drops_all_keys():
    limiter = _limiter(max_attempts=1)

    def _scenario():
        limiter.register_failure("a")
        limiter.register_failure("b")
        limiter.clear()
        return limiter.retry_after("a"), limiter.retry_after("b")

    assert await _in_worker_thread(_scenario) == (0.0, 0.0)


class DeadBackend:
    """Stands in for a Redis that was reachable at startup and died later."""

    def __getattr__(self, _name):
        async def _boom(*args, **kwargs):
            raise ConnectionError("Connection refused")

        return _boom


async def test_redis_going_down_does_not_break_logins():
    """A Redis that dies after the backend was picked must degrade, not raise.

    The backend is selected once at startup, so without this the login route
    turns every attempt into a 500 the moment Redis becomes unreachable.
    """
    limiter = _limiter(max_attempts=1, backend=DeadBackend())

    def _scenario():
        # Fails open: the attempt is allowed through rather than 500-ing.
        first = limiter.retry_after("ip")
        limiter.register_failure("ip")
        limiter.reset("ip")
        limiter.clear()
        return first, limiter.retry_after("ip")

    assert await _in_worker_thread(_scenario) == (0.0, 0.0)


def test_outside_a_worker_thread_degrades_instead_of_raising():
    """Called off an anyio worker thread the bridge can't run — fail open.

    This is the shape a future `async def` login route would take: the limiter
    stops throttling (one warning per call) rather than 500-ing every attempt.
    """
    limiter = _limiter(max_attempts=1)
    limiter.register_failure("ip")
    assert limiter.retry_after("ip") == 0.0


# --- SDK contract ------------------------------------------------------------


def test_sdk_backend_surface_matches_what_the_limiter_calls():
    """Pin the alpha SDK's API, because a rename would fail *open*.

    `RedisRateLimiter._guard` swallows every exception so a broken Redis can't
    break logins — which also means an `AttributeError` or `TypeError` from a
    renamed method would read as "allow the attempt" and silently disable
    throttling. fastapi-redis-sdk is 0.x, so this test fails loudly on the
    upgrade instead.
    """
    import inspect

    from redis_fastapi import RateLimitBackend, RateLimitResult

    for name, expected in (
        ("hit", {"identifier", "limit", "window"}),
        ("peek", {"identifier", "limit", "window"}),
        ("reset", {"identifier"}),
    ):
        method = getattr(RateLimitBackend, name)
        assert inspect.iscoroutinefunction(method), f"{name} must stay async"
        params = set(inspect.signature(method).parameters) - {"self"}
        assert expected <= params, f"{name} lost parameters: {expected - params}"

    # The two result fields retry_after() reads.
    fields = set(RateLimitResult.__dataclass_fields__)
    assert {"allowed", "retry_after"} <= fields

    # The scope segment used to build the login key namespace.
    assert "scope" in inspect.signature(RateLimitBackend.__init__).parameters
