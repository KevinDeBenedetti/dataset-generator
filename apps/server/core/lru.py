"""A least-recently-used cache bounded by the total weight of its entries.

Shared by the Hub reader (services/hub.py: tables, statistics, cards,
resolutions) and the Hub writer (services/huggingface.py: a dataset's pairs).
"""

import threading
from collections import OrderedDict
from typing import Any, Callable, Hashable, Optional, Tuple


class WeightedLRU:
    """Least-recently-used cache bounded by the total weight of its entries.

    ``budget`` is read on every insert, so a config change (or a test patching
    it) takes effect without rebuilding the cache. An entry heavier than the
    whole budget is simply not kept. Thread-safe.
    """

    def __init__(self, budget: Callable[[], int], weigh: Callable[[Any], int]):
        self._budget = budget
        self._weigh = weigh
        self._entries: "OrderedDict[Hashable, Tuple[int, Any]]" = OrderedDict()
        self._total = 0
        self._lock = threading.Lock()

    def get(self, key: Hashable) -> Optional[Any]:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            self._entries.move_to_end(key)
            return entry[1]

    def put(self, key: Hashable, value: Any) -> None:
        weight = max(1, self._weigh(value))
        with self._lock:
            old = self._entries.pop(key, None)
            if old is not None:
                self._total -= old[0]
            budget = self._budget()
            if weight > budget:
                return
            self._entries[key] = (weight, value)
            self._total += weight
            while self._total > budget and self._entries:
                _, (evicted, _) = self._entries.popitem(last=False)
                self._total -= evicted

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._total = 0
