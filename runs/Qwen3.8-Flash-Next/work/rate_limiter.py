"""Token-bucket rate limiter, per key, thread-safe, with idle-key expiry.

Rules implemented here:

* Token bucket per key with configurable ``capacity`` and ``refill_rate``
  (tokens added per second).
* Thread-safe for concurrent callers: all bucket state lives behind a single
  ``threading.Lock``.
* Keys that have not been used for ``idle_ttl`` seconds (default 600 = 10
  minutes) are dropped, so memory stays bounded.
* No background threads or timers: the expiry sweep is incremental and runs
  inside ordinary calls, evicting the keys at the head of the LRU order.
* Monotonic clock only (``time.monotonic`` by default). Elapsed times are
  clamped at zero, so a clock that jumps backwards cannot hand out tokens or
  corrupt a bucket.
* Lock discipline: the clock callable (user-supplied) is always invoked
  *before* the lock is taken, so no lock is ever held while user code runs or
  while any I/O would happen.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Callable

DEFAULT_IDLE_TTL = 600.0

__all__ = ["TokenBucketRateLimiter"]


class _Bucket:
    __slots__ = ("tokens", "last")

    def __init__(self, tokens: float, last: float) -> None:
        self.tokens = tokens
        self.last = last


class TokenBucketRateLimiter:
    def __init__(
        self,
        capacity: float,
        refill_rate: float,
        *,
        idle_ttl: float = DEFAULT_IDLE_TTL,
        clock: Callable[[], float] = time.monotonic,
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
        self._lock = threading.Lock()
        self._buckets: dict[str, _Bucket] = {}
        # LRU order by last activity: oldest first. Doubles as the sweep cursor.
        self._lru: "OrderedDict[str, None]" = OrderedDict()

    # ------------------------------------------------------------------
    # Public API. Each entry point reads the clock *outside* the lock.
    # ------------------------------------------------------------------
    def acquire(self, key: str, tokens: float = 1) -> bool:
        """Take ``tokens`` from ``key``'s bucket; True if it allowed them."""
        self._check_tokens(tokens)
        now = self._clock()
        with self._lock:
            self._sweep_locked(now)
            bucket = self._touch_locked(key, now)
            if bucket.tokens >= tokens:
                bucket.tokens -= tokens
                return True
            return False

    def check(self, key: str, tokens: float = 1) -> bool:
        """Return whether ``tokens`` could be taken right now, without taking.

        Pure peek: it does not modify bucket state, so it does not count as
        activity that would keep an idle key alive.
        """
        self._check_tokens(tokens)
        now = self._clock()
        with self._lock:
            self._sweep_locked(now)
            bucket = self._buckets.get(key)
            if bucket is None:
                return self._capacity >= tokens
            return self._peek(bucket, now) >= tokens

    def available(self, key: str) -> float:
        """Tokens currently available to ``key`` (full bucket if unseen)."""
        now = self._clock()
        with self._lock:
            self._sweep_locked(now)
            bucket = self._buckets.get(key)
            if bucket is None:
                return self._capacity
            return self._peek(bucket, now)

    def wait_time(self, key: str, tokens: float = 1) -> float:
        """Seconds ``key`` must wait for ``tokens``; ``inf`` if that can never
        happen because refill_rate is 0."""
        self._check_tokens(tokens)
        now = self._clock()
        with self._lock:
            self._sweep_locked(now)
            bucket = self._buckets.get(key)
            have = self._capacity if bucket is None else self._peek(bucket, now)
            deficit = tokens - have
            if deficit <= 0:
                return 0.0
            if self._refill_rate <= 0:
                return float("inf")
            return deficit / self._refill_rate

    def reset(self, key: str) -> bool:
        """Forget ``key`` entirely. Returns True if it was known."""
        with self._lock:
            return self._drop_locked(key)

    def clear(self) -> None:
        with self._lock:
            self._buckets.clear()
            self._lru.clear()

    def size(self) -> int:
        """Number of live keys (only keys past their idle TTL are removed)."""
        with self._lock:
            return len(self._buckets)

    def sweep(self) -> int:
        """Drop idle keys; returns how many were dropped. Ordinary calls do
        this implicitly."""
        now = self._clock()
        with self._lock:
            return self._sweep_locked(now)

    def __len__(self) -> int:
        return self.size()

    # ------------------------------------------------------------------
    # Internals. ``_..._locked`` helpers assume the lock is held. No user
    # code (including the clock) is ever called from here.
    # ------------------------------------------------------------------
    @staticmethod
    def _check_tokens(tokens: float) -> None:
        if tokens <= 0:
            raise ValueError("tokens must be > 0")

    def _peek(self, bucket: _Bucket, now: float) -> float:
        """Tokens ``bucket`` would hold at ``now``; does not modify it."""
        elapsed = now - bucket.last
        if elapsed <= 0:
            return bucket.tokens
        return min(self._capacity, bucket.tokens + elapsed * self._refill_rate)

    def _touch_locked(self, key: str, now: float) -> _Bucket:
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _Bucket(self._capacity, now)
            self._buckets[key] = bucket
        else:
            elapsed = now - bucket.last
            if elapsed > 0:
                bucket.tokens = min(self._capacity, bucket.tokens + elapsed * self._refill_rate)
                bucket.last = now
        # Re-order to the most-recently-used end of the LRU queue.
        self._lru.pop(key, None)
        self._lru[key] = None
        return bucket

    def _drop_locked(self, key: str) -> bool:
        existed = self._buckets.pop(key, None) is not None
        self._lru.pop(key, None)
        return existed

    def _sweep_locked(self, now: float) -> int:
        cutoff = now - self._idle_ttl
        dropped = 0
        buckets = self._buckets
        lru = self._lru
        while lru:
            key = next(iter(lru))
            bucket = buckets.get(key)
            if bucket is None:  # bookkeeping drift: heal and continue
                lru.popitem(last=False)
                continue
            if bucket.last >= cutoff:
                break
            lru.popitem(last=False)
            buckets.pop(key, None)
            dropped += 1
        return dropped
