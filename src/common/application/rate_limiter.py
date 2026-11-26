"""In-memory sliding-window rate limiter (per process, no external dependency)."""
import hashlib
import threading
import time
from collections import deque
from typing import Callable, Deque, Dict


def hashed_key(value: str) -> str:
    """Bound key size and avoid keeping raw identifiers (e.g. e-mails) in memory."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


class SlidingWindowRateLimiter:
    """Thread-safe sliding window counter with TTL based garbage collection.

    ``hit`` records an attempt only when it is allowed, so blocked callers do not extend
    their own penalty. State lives in process memory: with several workers each process
    enforces its own limits, and a restart resets all counters.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        max_keys: int = 50_000,
        sweep_interval_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.enabled = enabled
        self._max_keys = max_keys
        self._sweep_interval = sweep_interval_seconds
        self._clock = clock
        self._lock = threading.Lock()
        # key -> (window_seconds, timestamps). Insertion order doubles as LRU order.
        self._hits: Dict[str, tuple[float, Deque[float]]] = {}
        self._last_sweep = clock()

    def hit(self, key: str, limit: int, window_seconds: float) -> int:
        """Record an attempt. Returns 0 when allowed, else seconds until a retry can succeed."""
        if not self.enabled or limit <= 0:
            return 0
        now = self._clock()
        with self._lock:
            self._sweep(now)
            _, hits = self._hits.pop(key, (window_seconds, deque()))
            cutoff = now - window_seconds
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= limit:
                self._hits[key] = (window_seconds, hits)
                return max(1, int(hits[0] + window_seconds - now) + 1)
            hits.append(now)
            self._hits[key] = (window_seconds, hits)
            self._enforce_capacity()
            return 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._hits)

    def _sweep(self, now: float) -> None:
        if now - self._last_sweep < self._sweep_interval:
            return
        self._last_sweep = now
        expired = [
            key for key, (window, hits) in self._hits.items()
            if not hits or hits[-1] <= now - window
        ]
        for key in expired:
            del self._hits[key]

    def _enforce_capacity(self) -> None:
        # Bound memory under a flood of distinct keys: drop least recently used entries.
        overflow = len(self._hits) - self._max_keys
        for key in list(self._hits)[:max(0, overflow)]:
            del self._hits[key]
