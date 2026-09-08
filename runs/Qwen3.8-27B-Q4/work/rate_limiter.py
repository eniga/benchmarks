"""Per-key token-bucket rate limiter.

Properties:
- One token bucket per key, with configurable capacity and refill rate
  (tokens per second).
- Thread-safe: all state is guarded by a single ``threading.Lock``.
- Keys expire after ``idle_ttl`` seconds (default 600 = 10 minutes) of
  inactivity, so memory stays bounded. Cleanup happens opportunistically
  inside normal calls; there are no background threads or timers.
- Only ``time.monotonic()`` is used, so wall-clock changes cannot break it.
- Invariant: no operation ever holds the lock while performing I/O or
  calling user-supplied code. The limiter's public methods take only
  hashable values and do no I/O; the lock is held only around in-memory
  bookkeeping.
"""

from __future__ import annotations

import threading
import time
from typing import Any


class _Bucket:
    __slots__ = ("tokens", "updated")

    def __init__(self, capacity: float, now: float) -> None:
        self.tokens = float(capacity)
        self.updated = now


class TokenBucketRateLimiter:
    """Per-key token bucket rate limiter.

    Parameters
    ----------
    capacity:
        Maximum number of tokens a bucket can hold (burst size).
    refill_rate:
        Tokens added per second while the bucket is below capacity.
    idle_ttl:
        Seconds of inactivity after which a key's bucket is discarded.
        Defaults to 600 (10 minutes).
    """

    def __init__(self, capacity: float, refill_rate: float, idle_ttl: float = 600.0) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if refill_rate < 0:
            raise ValueError("refill_rate must be non-negative")
        if idle_ttl <= 0:
            raise ValueError("idle_ttl must be positive")
        self._capacity = float(capacity)
        self._refill_rate = float(refill_rate)
        self._idle_ttl = float(idle_ttl)
        self._buckets: dict[Any, _Bucket] = {}
        self._lock = threading.Lock()

    # -- public API -------------------------------------------------------

    def allow(self, key: Any, n: int = 1, now: float | None = None) -> bool:
        """Try to consume ``n`` tokens for ``key``.

        Returns True and consumes the tokens if enough are available,
        otherwise returns False and consumes nothing. ``now`` is a test
        hook; production callers leave it as None and the monotonic
        clock is used.
        """
        if n <= 0:
            raise ValueError("n must be positive")
        if now is None:
            now = time.monotonic()
        with self._lock:
            self._sweep_locked(now)
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(self._capacity, now)
                self._buckets[key] = bucket
            # Refill advances ``bucket.updated`` to ``now`` only when
            # ``now`` is newer; the timestamp must never move backwards.
            # Different threads may hold slightly stale monotonic readings,
            # and a backwards update would let the same time window refill
            # twice. Any access (granted or denied) at a newer timestamp
            # therefore counts as activity.
            self._refill_locked(bucket, now)
            if bucket.tokens >= n:
                bucket.tokens -= n
                return True
            return False

    def try_acquire(self, key: Any, n: int = 1, now: float | None = None) -> bool:
        """Alias for :meth:`allow`."""
        return self.allow(key, n=n, now=now)

    def remaining(self, key: Any, now: float | None = None) -> float:
        """Tokens currently available for ``key`` (without consuming any).

        Note: this call also refreshes the key's activity timestamp and
        may trigger the idle sweep, like any other call.
        """
        if now is None:
            now = time.monotonic()
        with self._lock:
            self._sweep_locked(now)
            bucket = self._buckets.get(key)
            if bucket is None:
                return self._capacity
            self._refill_locked(bucket, now)
            return bucket.tokens

    def live_keys(self, now: float | None = None) -> int:
        """Number of buckets currently held in memory (after a sweep).

        ``now`` is a test hook; production callers leave it as None.
        """
        if now is None:
            now = time.monotonic()
        with self._lock:
            self._sweep_locked(now)
            return len(self._buckets)

    # -- internals (caller holds self._lock) ------------------------------

    def _refill_locked(self, bucket: _Bucket, now: float) -> None:
        elapsed = now - bucket.updated
        if elapsed > 0:
            bucket.tokens = min(self._capacity, bucket.tokens + elapsed * self._refill_rate)
            bucket.updated = now

    def _sweep_locked(self, now: float) -> None:
        """Drop buckets idle for longer than ``idle_ttl``.

        Runs on every public call, so no background thread is needed.
        Cost is O(live keys), which is bounded by the number of distinct
        keys active within the last ``idle_ttl`` seconds.
        """
        expired = [k for k, b in self._buckets.items() if now - b.updated > self._idle_ttl]
        for k in expired:
            del self._buckets[k]
