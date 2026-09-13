"""Per-key token-bucket rate limiter.

Requirements met:
- Token bucket, per-key, configurable capacity and refill rate (tokens/sec).
- Thread-safe: a single lock guards the bucket table; all state transitions
  happen atomically under it.
- Keys expire after 10 minutes of inactivity; cleanup is opportunistic and
  happens during normal calls (no background threads or timers).
- Uses ``time.monotonic`` only (injectable for tests); immune to wall-clock
  changes.
- Invariant: no operation performs I/O or calls user-supplied code while
  holding the lock. The critical sections contain only arithmetic and
  dict/list operations on internal state.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

INACTIVE_TTL = 600.0  # seconds of inactivity before a key is eligible for removal
_SWEEP_INTERVAL = 60.0  # minimum seconds between full sweeps
_SWEEP_EAGER_AT = 1024  # sweep immediately once the table grows this large


@dataclass
class _Bucket:
    tokens: float
    last_refill: float  # monotonic timestamp of last refill computation
    last_seen: float    # monotonic timestamp of last access (expiry basis)


class TokenBucketRateLimiter:
    def __init__(
        self,
        capacity: float,
        refill_rate: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        if refill_rate < 0:
            raise ValueError("refill_rate must be >= 0")
        self._capacity = float(capacity)
        self._refill_rate = float(refill_rate)
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: dict[str, _Bucket] = {}
        self._last_sweep = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def allow(self, key: str, n: float = 1.0) -> bool:
        """Try to consume ``n`` tokens for ``key``.

        Returns True (and consumes) if enough tokens are available,
        False otherwise. A first-time key starts with a full bucket.
        """
        if n < 0:
            raise ValueError("n must be >= 0")
        now = self._clock()
        with self._lock:
            self._sweep_locked(now)
            bucket = self._buckets.get(key)
            if bucket is None:
                if n > self._capacity:
                    return False  # never fits; do not create a bucket for it
                self._buckets[key] = _Bucket(
                    tokens=self._capacity - n, last_refill=now, last_seen=now
                )
                return True
            self._refill_locked(bucket, now)
            bucket.last_seen = now
            if bucket.tokens >= n:
                bucket.tokens -= n
                return True
            return False

    # Alias for readability.
    try_acquire = allow

    def available(self, key: str) -> float:
        """Tokens currently available for ``key`` (does not consume)."""
        now = self._clock()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                return self._capacity
            self._refill_locked(bucket, now)
            return bucket.tokens

    def reset(self, key: str) -> None:
        """Drop all state for ``key`` (next call starts with a full bucket)."""
        with self._lock:
            self._buckets.pop(key, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._buckets)

    # ------------------------------------------------------------------
    # Internal helpers -- caller must hold self._lock
    # ------------------------------------------------------------------

    def _refill_locked(self, bucket: _Bucket, now: float) -> None:
        if self._refill_rate > 0.0:
            elapsed = now - bucket.last_refill
            if elapsed > 0.0:
                bucket.tokens = min(
                    self._capacity, bucket.tokens + elapsed * self._refill_rate
                )
                bucket.last_refill = now

    def _sweep_locked(self, now: float) -> None:
        """Remove keys idle for more than INACTIVE_TTL.

        Bounded cost: a full O(n) pass runs at most once per
        _SWEEP_INTERVAL seconds, or immediately when the table is large.
        """
        if len(self._buckets) < _SWEEP_EAGER_AT and (
            now - self._last_sweep < _SWEEP_INTERVAL
        ):
            return
        self._last_sweep = now
        stale = [
            key
            for key, bucket in self._buckets.items()
            if now - bucket.last_seen > INACTIVE_TTL
        ]
        for key in stale:
            del self._buckets[key]
