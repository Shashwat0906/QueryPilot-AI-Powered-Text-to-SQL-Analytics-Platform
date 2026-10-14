"""Tiny in-memory sliding-window rate limiter (per client IP).

Protects the LLM budget from accidental request floods. Like the cache it is
per-process; behind several instances you would move it to Redis or the
API gateway.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> tuple[bool, float]:
        """Returns (allowed, seconds_until_retry)."""
        if self.limit <= 0:
            return True, 0.0
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False, round(self.window - (now - hits[0]), 1)
            hits.append(now)
            return True, 0.0
