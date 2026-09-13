"""Thread-safe, per-key token bucket rate limiter.

Properties
----------
- Token bucket per key with configurable capacity and refill rate
  (tokens per second).
- Thread-safe under concurrent access: one lock guards the bucket table
  and all bucket state; every public method is atomic.
- Keys expire after ``idle_ttl`` seconds (default 600) of inactivity so
  memory stays bounded.
- No background threads or timers: cleanup happens opportunistically
  inside normal calls (a sweep runs whenever the table grows to
  ``sweep_threshold`` entries).
- Uses a monotonic clock only (``time.monotonic`` by default, injectable
  for tests); a backward clock jump can never grant extra tokens.

Invariant
---------
No operation ever holds a lock while performing I/O or calling
user-supplied code. This module performs no I/O and calls no user code
at all, so the invariant holds by construction.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Dict, Optional


class _Bucket:
    """Internal per-key bucket state. Only valid while the limiter lock is held."""

    __slots__ = ("tokens", "last_refill", "last_access")

    def __init__(self, tokens: float, now: float) -> None:
        self.tokens = tokens
        self.last_refill = now
        self.last_access = now


class TokenBucketRateLimiter:
    def __init__(
        self,
        capacity: float,
        refill_rate: float,
        *,
        idle_ttl: float = 600.0,
        clock: Callable[[], float] = time.monotonic,
        sweep_threshold: int = 1024,
    ) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        if refill_rate < 0:
            raise ValueError("refill_rate must be >= 0")
        if idle_ttl <= 0:
            raise ValueError("idle_ttl must be > 0")
        self._capacity = float(capacity)
        self._refill_rate = float(refill_rate)
        self._idle_ttl = float(idle_ttl)
        self._clock = clock
        self._sweep_threshold = int(sweep_threshold)
        self._lock = threading.Lock()
        self._buckets: Dict[str, _Bucket] = {}

    # -- internals (caller must hold self._lock) -------------------------

    def _refill(self, bucket: _Bucket, now: float) -> None:
        elapsed = now - bucket.last_refill
        if elapsed > 0:  # guard: a backward clock jump grants nothing
            bucket.tokens = min(
                self._capacity, bucket.tokens + elapsed * self._refill_rate
            )
            bucket.last_refill = now

    def _sweep_expired(self, now: float) -> None:
        expired = [
            key
            for key, bucket in self._buckets.items()
            if now - bucket.last_access > self._idle_ttl
        ]
        for key in expired:
            del self._buckets[key]

    # -- public API -------------------------------------------------------

    def consume(self, key: str, tokens: float = 1.0) -> bool:
        """Try to consume ``tokens`` for ``key``.

        Returns True and debits the bucket if enough tokens are available
        after refill, otherwise False (state unchanged except bookkeeping).
        """
        if tokens < 0:
            raise ValueError("tokens must be >= 0")
        if tokens > self._capacity:
            return False
        now = self._clock()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                if len(self._buckets) >= self._sweep_threshold:
                    self._sweep_expired(now)
                bucket = self._buckets.get(key)
                if bucket is None:
                    bucket = self._buckets[key] = _Bucket(self._capacity, now)
            self._refill(bucket, now)
            bucket.last_access = now
            if bucket.tokens >= tokens:
                bucket.tokens -= tokens
                return True
            return False

    # Convenience alias.
    allow = consume

    def available(self, key: str) -> float:
        """Tokens currently available for ``key`` (after refill)."""
        now = self._clock()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                return self._capacity
            self._refill(bucket, now)
            bucket.last_access = now
            return bucket.tokens

    def reset(self, key: Optional[str] = None) -> None:
        """Drop one key's bucket, or all of them when ``key`` is None."""
        with self._lock:
            if key is None:
                self._buckets.clear()
            else:
                self._buckets.pop(key, None)

    def __len__(self) -> int:
        """Number of live (not yet swept) buckets."""
        with self._lock:
            return len(self._buckets)
