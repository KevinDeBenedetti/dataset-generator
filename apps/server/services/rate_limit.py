"""In-process sliding-window rate limiting.

Used to throttle brute-force login attempts. State lives in this process only,
so it is NOT shared across multiple uvicorn workers or replicas — it's a first
defensive layer, not a distributed quota. Put a real store (Redis) or an
edge/WAF limit in front for multi-worker deployments.
"""

import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional


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


# Process-global limiter for the login endpoint, sized from config.
from server.core.config import config  # noqa: E402 — avoid a circular import at top

login_rate_limiter = SlidingWindowRateLimiter(
    max_attempts=config.auth_login_max_attempts,
    window_seconds=config.auth_login_window_seconds,
)
