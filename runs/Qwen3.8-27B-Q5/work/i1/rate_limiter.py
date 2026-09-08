"""Thread-safe per-key token-bucket rate limiter.

Properties
----------
- Per-key token bucket with configurable ``capacity`` and refill ``rate``
  (tokens per second).
- Thread-safe: all shared state is guarded by a single ``threading.Lock``.
- Keys expire after ``expiry`` seconds (default 10 minutes) of inactivity.
  Expired buckets are removed lazily during normal calls; there are no
  background threads or timers.
- Time is read from a monotonic clock (``time.monotonic`` by default, or an
  injected stand-in for tests), so wall-clock changes cannot break it.
- Invariant: no operation holds the lock while performing I/O or calling
  user-supplied code. The clock is read *before* the lock is acquired, and
  the only work done under the lock is arithmetic on in-memory state.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

DEFAULT_EXPIRY_SECONDS = 600.0  # 10 minutes


class _Bucket:
    __slots__ = ("tokens", "last_refill", "last_used")

    def __init__(self, capacity: float, now: float) -> None:
        self.tokens = capacity
        self.last_refill = now
        self.last_used = now


class RateLimiter:
    def __init__(
        self,
        capacity: float,
        rate: float,
        *,
        expiry: float = DEFAULT_EXPIRY_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        if rate < 0:
            raise ValueError("rate must be >= 0")
        if expiry <= 0:
            raise ValueError("expiry must be > 0")
        self._capacity = float(capacity)
        self._rate = float(rate)
        self._expiry = float(expiry)
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: dict[str, _Bucket] = {}

    def allow(self, key: str, tokens: float = 1.0) -> bool:
        """Try to consume ``tokens`` from ``key``'s bucket.

        Returns True if the request is allowed, False if it is rate-limited.
        A request for more tokens than the bucket capacity is always denied.
        """
        if tokens <= 0:
            return True
        if tokens > self._capacity:
            return False
        now = self._clock()
        with self._lock:
            self._sweep_locked(now)
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(self._capacity, now)
                self._buckets[key] = bucket
            self._refill_locked(bucket, now)
            bucket.last_used = now
            if bucket.tokens >= tokens:
                bucket.tokens -= tokens
                return True
            return False

    def remaining(self, key: str) -> float:
        """Tokens currently available for ``key`` (does not consume any)."""
        now = self._clock()
        with self._lock:
            self._sweep_locked(now)
            bucket = self._buckets.get(key)
            if bucket is None:
                return self._capacity
            self._refill_locked(bucket, now)
            bucket.last_used = now
            return bucket.tokens

    def active_keys(self) -> int:
        """Number of buckets not yet expired (sweeps first)."""
        now = self._clock()
        with self._lock:
            self._sweep_locked(now)
            return len(self._buckets)

    # -- internals; caller must hold ``_lock`` --------------------------

    def _refill_locked(self, bucket: _Bucket, now: float) -> None:
        elapsed = now - bucket.last_refill
        if elapsed > 0 and self._rate > 0:
            bucket.tokens = min(self._capacity, bucket.tokens + self._rate * elapsed)
            bucket.last_refill = now

    def _sweep_locked(self, now: float) -> None:
        if not self._buckets:
            return
        expired = [
            key
            for key, bucket in self._buckets.items()
            if now - bucket.last_used >= self._expiry
        ]
        for key in expired:
            del self._buckets[key]
