"""Unit tests for the sliding-window rate limiter."""

from server.services.rate_limit import SlidingWindowRateLimiter


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
