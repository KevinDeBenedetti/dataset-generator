"""Unit tests for the sliding-window rate limiter."""

import fnmatch

from server.services.rate_limit import (
    RedisSlidingWindowRateLimiter,
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


# --- Redis-backed limiter ----------------------------------------------------


class FakeRedis:
    """Minimal in-memory stand-in for the redis sorted-set commands used."""

    def __init__(self):
        self.zsets: dict[str, dict[str, float]] = {}

    def zadd(self, name, mapping):
        self.zsets.setdefault(name, {}).update(mapping)

    def zremrangebyscore(self, name, min, max):
        z = self.zsets.get(name)
        if not z:
            return
        for member in [m for m, s in z.items() if min <= s <= max]:
            del z[member]

    def zcard(self, name):
        return len(self.zsets.get(name, {}))

    def zrange(self, name, start, end, withscores=False):
        items = sorted(self.zsets.get(name, {}).items(), key=lambda kv: kv[1])
        sliced = items[start:] if end == -1 else items[start : end + 1]
        return sliced if withscores else [m for m, _ in sliced]

    def expire(self, name, seconds):  # noqa: ARG002 — TTL is a no-op in tests
        return None

    def delete(self, *names):
        for n in names:
            self.zsets.pop(n, None)

    def scan_iter(self, match=None):
        return [
            k for k in list(self.zsets) if match is None or fnmatch.fnmatch(k, match)
        ]


def test_redis_blocks_after_max():
    limiter = RedisSlidingWindowRateLimiter(
        max_attempts=2, window_seconds=60, client=FakeRedis()
    )
    assert limiter.retry_after("ip") == 0.0
    limiter.register_failure("ip")
    limiter.register_failure("ip")
    blocked = limiter.retry_after("ip")
    assert blocked > 0
    assert blocked <= 60


def test_redis_reset_clears_a_key():
    limiter = RedisSlidingWindowRateLimiter(
        max_attempts=1, window_seconds=60, client=FakeRedis()
    )
    limiter.register_failure("ip")
    assert limiter.retry_after("ip") > 0
    limiter.reset("ip")
    assert limiter.retry_after("ip") == 0.0


def test_redis_keys_are_independent():
    limiter = RedisSlidingWindowRateLimiter(
        max_attempts=1, window_seconds=60, client=FakeRedis()
    )
    limiter.register_failure("a")
    assert limiter.retry_after("a") > 0
    assert limiter.retry_after("b") == 0.0


def test_redis_clear_drops_all_keys():
    client = FakeRedis()
    limiter = RedisSlidingWindowRateLimiter(
        max_attempts=1, window_seconds=60, client=client
    )
    limiter.register_failure("a")
    limiter.register_failure("b")
    limiter.clear()
    assert limiter.retry_after("a") == 0.0
    assert limiter.retry_after("b") == 0.0
