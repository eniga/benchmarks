"""Per-key token-bucket rate limiter.

Properties
----------
* Token bucket per key, with configurable capacity and refill rate.
* Thread-safe: all shared state is guarded by a single lock.
* Keys not touched for ``expiry`` seconds (default 600 = 10 minutes) are
  evicted, so memory stays bounded.
* No background threads or timers: eviction happens inside normal calls,
  amortized (a full scan runs at most once per ``cleanup_interval``).
* Monotonic clock only (``time.monotonic`` by default), so system clock
  changes cannot affect the limiter. A backward jump of the injected clock
  is tolerated: it simply refills nothing.

Invariant
---------
No operation ever holds the lock while performing I/O or calling
user-supplied code. The only user-supplied callable is the clock, and it is
always invoked *before* the lock is acquired.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    last_refill: float
    last_used: float


class TokenBucketRateLimiter:
    """Per-key token bucket.

    Parameters
    ----------
    capacity:
        Maximum number of tokens a bucket can hold (burst size).
    refill_rate:
        Tokens added per second.
    expiry:
        Seconds of inactivity after which a key's bucket is evicted.
        "Touched" means an :meth:`allow` call (allowed or denied).
    cleanup_interval:
        Minimum seconds between full expiry scans. A stale key therefore
        lives at most ``expiry + cleanup_interval`` seconds.
    clock:
        Zero-argument callable returning the current time. Must be
        monotonic; defaults to :func:`time.monotonic`.
    """

    def __init__(
        self,
        capacity: float,
        refill_rate: float,
        expiry: float = 600.0,
        cleanup_interval: float = 30.0,
        clock=time.monotonic,
    ) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        if refill_rate < 0:
            raise ValueError("refill_rate must be >= 0")
        if expiry <= 0:
            raise ValueError("expiry must be > 0")
        if cleanup_interval <= 0:
            raise ValueError("cleanup_interval must be > 0")
        self._capacity = float(capacity)
        self._refill_rate = float(refill_rate)
        self._expiry = float(expiry)
        self._cleanup_interval = float(cleanup_interval)
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: dict[str, _Bucket] = {}
        self._last_cleanup = clock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def allow(self, key: str, tokens: float = 1.0) -> bool:
        """Try to consume ``tokens`` from ``key``'s bucket.

        Returns True and debits the bucket if enough tokens are available,
        False otherwise. Every call counts as activity for the key (it
        refreshes the key's expiry).
        """
        if tokens <= 0:
            raise ValueError("tokens must be > 0")
        now = self._clock()  # user-supplied callable: outside the lock
        with self._lock:
            self._cleanup_locked(now)
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(self._capacity, now, now)
                self._buckets[key] = bucket
            self._refill_locked(bucket, now)
            bucket.last_used = now
            if bucket.tokens >= tokens - 1e-12:
                bucket.tokens -= tokens
                return True
            return False

    def remaining(self, key: str) -> float:
        """Tokens currently available for ``key`` (refilled up to now).

        A probe: does not count as activity for the key.
        """
        now = self._clock()  # user-supplied callable: outside the lock
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                return self._capacity
            self._refill_locked(bucket, now)
            return bucket.tokens

    def __len__(self) -> int:
        """Number of live keys (buckets not yet evicted)."""
        with self._lock:
            return len(self._buckets)

    # ------------------------------------------------------------------
    # Internals -- caller must hold self._lock
    # ------------------------------------------------------------------

    def _refill_locked(self, bucket: _Bucket, now: float) -> None:
        elapsed = now - bucket.last_refill
        if elapsed > 0:
            bucket.tokens = min(
                self._capacity, bucket.tokens + elapsed * self._refill_rate
            )
            bucket.last_refill = now

    def _cleanup_locked(self, now: float) -> None:
        if now - self._last_cleanup < self._cleanup_interval:
            return
        self._last_cleanup = now
        stale = [
            key
            for key, bucket in self._buckets.items()
            if now - bucket.last_used >= self._expiry
        ]
        for key in stale:
            del self._buckets[key]
