"""Thread-safe, per-key token-bucket rate limiter.

Design notes
------------
* Per-key token buckets with configurable ``capacity`` and ``refill_rate``
  (tokens per second).
* Thread-safe: all mutation of the shared ``_buckets`` dict happens while
  holding ``_lock``.
* Keys expire after ``ttl`` seconds of inactivity; idle keys are reclaimed by
  ``_maybe_cleanup_locked`` which runs opportunistically during normal calls
  (no background threads or timers).
* Monotonic clock only (``time.monotonic`` by default).  A monotonic clock can
  never move backwards, so elapsed deltas are always non-negative and the
  limiter is immune to wall-clock jumps (NTP adjustments, manual changes).
* Invariant: no operation holds ``_lock`` while performing I/O or calling
  user-supplied code.  The optional ``refresh`` callback (which may do I/O) is
  invoked strictly between two lock acquisitions.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

DEFAULT_TTL = 600.0  # 10 minutes of inactivity before a key may be reclaimed.
_CLEANUP_THRESHOLD = 2000  # trigger a sweep once the table grows past this.
_DEFAULT_SWEEP_INTERVAL = 256  # sweep this often during normal calls


class _Bucket:
    __slots__ = ("capacity", "tokens", "refill_rate", "last_refill")

    def __init__(
        self,
        capacity: float,
        tokens: float,
        refill_rate: float,
        now: float,
    ) -> None:
        self.capacity = capacity
        self.tokens = tokens
        self.refill_rate = refill_rate
        self.last_refill = now


class RateLimiter:
    def __init__(
        self,
        capacity: float,
        refill_rate: float,
        ttl: float = DEFAULT_TTL,
        clock: Callable[[], float] = time.monotonic,
        refresh: Optional[Callable[[str], Optional[float]]] = None,
        sweep_interval: int = _DEFAULT_SWEEP_INTERVAL,
    ) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if refill_rate < 0:
            raise ValueError("refill_rate must be non-negative")
        self._capacity = float(capacity)
        self._refill_rate = float(refill_rate)
        self._ttl = float(ttl)
        self._clock = clock
        # Optional user hook: key -> initial token count (or None -> default).
        self._refresh = refresh
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()
        self._calls_since_sweep = 0
        self._sweep_interval = max(1, int(sweep_interval))

    # -- clock ---------------------------------------------------------------
    def _now(self) -> float:
        return self._clock()

    # -- lock helpers (caller must hold _lock) -------------------------------
    def _refill_locked(self, bucket: _Bucket, now: float) -> None:
        elapsed = now - bucket.last_refill
        if elapsed > 0:  # monotonic clock guarantees elapsed >= 0; guard anyway
            new_tokens = bucket.tokens + elapsed * bucket.refill_rate
            bucket.tokens = min(self._capacity, new_tokens)
            bucket.last_refill = now

    def _maybe_cleanup_locked(self) -> int:
        now = self._now()
        expired = [k for k, b in self._buckets.items() if now - b.last_refill > self._ttl]
        for k in expired:
            del self._buckets[k]
        return len(expired)

    # -- public API ----------------------------------------------------------
    def try_acquire(self, key: str, amount: int = 1) -> bool:
        """Consume ``amount`` tokens for ``key``; return True if allowed.

        The optional ``refresh`` callback, if any, is called at most once per
        key and only while ``_lock`` is released.
        """
        now = self._now()
        did_refresh = False
        start_tokens: Optional[float] = None

        # 1) If a refresh hook exists, reserve a placeholder under the lock so
        #    concurrent callers for the same brand-new key do not each refresh.
        if self._refresh is not None:
            reserved = False
            with self._lock:
                if self._buckets.get(key) is None:
                    self._buckets[key] = _Bucket(self._capacity, 0.0, self._refill_rate, now)
                    reserved = True
            # 2) OUTSIDE the lock: run any user-supplied code / I/O.
            if reserved:
                try:
                    start_tokens = self._refresh(key)
                except Exception:
                    start_tokens = None
                if start_tokens is None:
                    start_tokens = self._capacity  # fail open on refresh error
                did_refresh = True

        # 3) Back under lock: (re)initialize, refill, consume, sweep.
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                # A concurrent non-refresh path created it; treat as fresh.
                bucket = _Bucket(self._capacity, self._capacity, self._refill_rate, now)
                self._buckets[key] = bucket
            elif (now - bucket.last_refill) > self._ttl:
                # Expired by inactivity: discard stale state (bounds memory) and
                # start a fresh bucket at the proper initial token count.
                fresh = start_tokens if did_refresh else self._capacity
                self._buckets[key] = _Bucket(self._capacity, fresh, self._refill_rate, now)
                bucket = self._buckets[key]
            elif did_refresh:
                bucket.tokens = min(self._capacity, float(start_tokens))
                bucket.last_refill = now

            self._refill_locked(bucket, now)

            allowed = bucket.tokens >= amount
            if allowed:
                bucket.tokens -= amount
                bucket.last_refill = now

            self._calls_since_sweep += 1
            if (
                self._calls_since_sweep >= self._sweep_interval
                or len(self._buckets) > _CLEANUP_THRESHOLD
            ):
                self._calls_since_sweep = 0
                self._maybe_cleanup_locked()

        return allowed

    def available(self, key: str) -> float:
        """Return current available tokens for ``key`` (may be fractional)."""
        now = self._now()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                return self._capacity
            self._refill_locked(bucket, now)
            return bucket.tokens

    def __len__(self) -> int:
        with self._lock:
            return len(self._buckets)
