"""TTL+LRU cache and sliding-window rate limiter."""

import threading
import time
from collections import OrderedDict


class TTLLRU:
    """Tiny TTL + LRU cache.  Evicts the oldest entry when full and drops
    expired entries on read.  Stored values may be anything — including
    empty strings — since ``None`` is reserved as the miss sentinel."""

    def __init__(self, ttl, maxsize):
        self.ttl = ttl
        self.maxsize = maxsize
        self._store: OrderedDict = OrderedDict()

    def get(self, key, now):
        item = self._store.get(key)
        if item is None:
            return None
        ts, value = item
        if now - ts > self.ttl:
            del self._store[key]
            return None
        self._store.move_to_end(key)
        return value

    def set(self, key, value, now):
        self._store[key] = (now, value)
        self._store.move_to_end(key)
        while len(self._store) > self.maxsize:
            self._store.popitem(last=False)


class RateLimiter:
    """Sliding-window per-key limiter backed by an in-process dict.  Good
    enough to deter abuse on a single instance; state is not shared across
    serverless replicas.  Thread-safe via an internal lock so concurrent
    requests in the thread pool can't drop updates."""

    def __init__(self, max_calls, period):
        self.max_calls = max_calls
        self.period = period
        self._hits: dict = {}
        self._sweep_at = 0.0
        self._lock = threading.Lock()

    def allow(self, key, now=None):
        now = now if now is not None else time.time()
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if now - t < self.period]
            blocked = len(hits) >= self.max_calls
            if not blocked:
                hits.append(now)
            self._hits[key] = hits
            # Sweep stale keys once per period so the dict can't grow unboundedly
            # under low-rate traffic from many distinct clients.
            if now >= self._sweep_at:
                self._hits = {
                    k: v for k, v in self._hits.items()
                    if v and now - v[-1] < self.period
                }
                self._sweep_at = now + self.period
            return not blocked
