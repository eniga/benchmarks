"""Per-key token-bucket rate limiter.

Design notes
------------
* One bucket per key. Each bucket holds at most ``capacity`` tokens and
  refills continuously at ``refill_rate`` tokens per second. Refill is
  computed lazily from the elapsed monotonic time; nothing runs in the
  background.
* Thread-safe: a single ``threading.Lock`` guards all bucket state.
* Keys expire after ``expiry`` seconds (default 600 = 10 minutes) of
  inactivity. Expired keys are removed opportunistically: a sweep runs at
  most once per ``cleanup_interval`` seconds, triggered from normal calls
  (``allow``). No background threads or timers are used.
* Only a monotonic clock is used (``time.monotonic`` by default), so
  wall-clock adjustments can never break refill or expiry math.
* Invariant: no operation ever holds a lock while performing I/O or
  calling user-supplied code. Everything executed under the lock is pure
  arithmetic and dictionary manipulation.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

DEFAULT_EXPIRY = 600.0  # 10 minutes of inactivity
DEFAULT_CLEANUP_INTERVAL = 30.0  # seconds between opportunistic sweeps

_EPS = 1e-9


@dataclass
class _Bucket:
    tokens: float
    last_refill: float  # monotonic timestamp of last refill computation
    last_seen: float    # monotonic timestamp of last activity on this key


class TokenBucketRateLimiter:
    """Thread-safe per-key token bucket rate limiter.

    Parameters
    ----------
    capacity:
        Maximum number of tokens a bucket can hold (burst size). Must be > 0.
    refill_rate:
        Tokens added per second. Must be >= 0. A rate of 0 means the bucket
        never refills.
    expiry:
        Seconds of inactivity after which a key's bucket is eligible for
        removal. Default 600 (10 minutes).
    cleanup_interval:
        Minimum seconds between opportunistic expiry sweeps. Default 30.
    clock:
        Monotonic clock callable. Defaults to ``time.monotonic``; injectable
        for testing.
    """

    def __init__(
        self,
        capacity: float,
        refill_rate: float,
        *,
        expiry: float = DEFAULT_EXPIRY,
        cleanup_interval: float = DEFAULT_CLEANUP_INTERVAL,
        clock: Callable[[], float] = time.monotonic,
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
        self._last_sweep = 0.0

    # ------------------------------------------------------------------
    # internals -- caller must hold self._lock
    # ------------------------------------------------------------------

    def _sweep_locked(self, now: float) -> None:
        """Remove buckets inactive for longer than ``expiry``.

        Pure dict work; no I/O, no user code. Rate-limited so that a hot
        path does not pay an O(n) scan on every call.
        """
        if now - self._last_sweep < self._cleanup_interval:
            return
        self._last_sweep = now
        stale = [
            key
            for key, bucket in self._buckets.items()
            if now - bucket.last_seen > self._expiry
        ]
        for key in stale:
            del self._buckets[key]

    def _refill_locked(self, bucket: _Bucket, now: float) -> None:
        elapsed = now - bucket.last_refill
        if elapsed > 0.0:
            bucket.tokens = min(
                self._capacity, bucket.tokens + elapsed * self._refill_rate
            )
            bucket.last_refill = now

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def allow(self, key: str, tokens: float = 1.0) -> bool:
        """Try to consume ``tokens`` from ``key``'s bucket.

        Returns True if the request was granted (tokens were consumed),
        False if the bucket did not have enough tokens. A request for more
        tokens than ``capacity`` is always denied.

        This is the only operation that counts as "activity" for expiry
        purposes.
        """
        if tokens < 0:
            raise ValueError("tokens must be >= 0")
        if tokens > self._capacity:
            return False
        now = self._clock()
        with self._lock:
            self._sweep_locked(now)
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(
                    tokens=self._capacity, last_refill=now, last_seen=now
                )
                self._buckets[key] = bucket
            else:
                self._refill_locked(bucket, now)
                bucket.last_seen = now
            if bucket.tokens + _EPS >= tokens:
                bucket.tokens -= tokens
                return True
            return False

    def wait_time(self, key: str, tokens: float = 1.0) -> float:
        """Seconds until ``tokens`` would be available for ``key``.

        Returns 0.0 if the tokens are available now, ``inf`` if they never
        will be (request exceeds capacity, or refill_rate is 0 with a
        deficit). This query does not consume tokens and does not count as
        activity for expiry purposes.
        """
        if tokens < 0:
            raise ValueError("tokens must be >= 0")
        if tokens > self._capacity:
            return float("inf")
        now = self._clock()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                return 0.0  # a fresh bucket starts full
            self._refill_locked(bucket, now)
            deficit = tokens - bucket.tokens
            if deficit <= _EPS:
                return 0.0
            if self._refill_rate == 0.0:
                return float("inf")
            return deficit / self._refill_rate

    def size(self) -> int:
        """Number of live buckets (for diagnostics/testing)."""
        with self._lock:
            return len(self._buckets)
