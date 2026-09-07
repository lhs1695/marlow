"""In-memory rate limit and input length. Not a multi-tenant product."""

from __future__ import annotations

import time
from collections import defaultdict, deque

MAX_INPUT_CHARS = 4000
RATE_LIMIT_MAX = 60
RATE_LIMIT_WINDOW_S = 60.0


class MemoryRateLimiter:
    def __init__(self, *, max_hits: int = RATE_LIMIT_MAX, window_s: float = RATE_LIMIT_WINDOW_S) -> None:
        self.max_hits = max_hits
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        bucket = self._hits[key]
        cutoff = now - self.window_s
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= self.max_hits:
            return False
        bucket.append(now)
        return True
