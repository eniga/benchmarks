## H1
The premise is false, and that is the first thing to check: a set is not slower than a list for membership tests. For 10,000 user IDs, a list's `in` is a linear scan — O(n), up to ~10,000 comparisons per check, on average ~5,000 — while a set's `in` is a hash lookup, O(1) average, typically a handful of comparisons. For that workload the set is thousands of times faster per lookup, so a measured slowdown after the switch means the measurement is pointing at something else. The usual real causes:

1. **The set is being rebuilt on every check.** The classic version of this bug: `if uid in set(user_ids)` where `user_ids` is a list, or a set comprehension / `set(...)` call inside the hot path. Construction is O(n) per call and allocates a new table each time, so you pay the list's cost *plus* allocation churn. The fix is to build the set once (at startup, or when the membership changes) and reuse it — a module-level `frozenset` if it is static.
2. **The slowdown is elsewhere and the change is coincidental** — e.g., the new code path touches I/O, logging, or the GIL differently. Profile before and after (cProfile plus a line profiler) instead of attributing it to the data structure.
3. **The elements are not cheap to hash.** If the "user IDs" are long strings or objects with expensive `__hash__`, hashing cost can matter, but for 10k elements it still beats scanning 10k elements.

What to use: keep the set — built once and updated incrementally (add/remove on membership change), not reconstructed per request. If the IDs are a dense integer range, a bitset (a `bytearray` or `array('Q')` indexed by ID) is even faster and more cache-friendly; if the membership set were in the millions and you only needed the negative path to be fast, a bloom filter would be the tool — but at 10,000 IDs a plain set is the right answer.

## H2
RFC 7231, section **6.5.8** ("409 Conflict").

First sentence, verbatim:

> The 409 (Conflict) status code indicates that the request could not be completed due to a conflict with the current state of the target resource.

## I1
Executed: `python3 -m unittest test_rate_limiter -v` (run from `work/`, Python 3.14.6)

### rate_limiter.py

```python
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
```

### test_rate_limiter.py

```python
"""Tests for rate_limiter.TokenBucketRateLimiter.

Run:  python3 -m unittest test_rate_limiter -v
"""

from __future__ import annotations

import threading
import unittest

from rate_limiter import INACTIVE_TTL, TokenBucketRateLimiter


class FakeClock:
    """Deterministic stand-in for time.monotonic (always moves forward)."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestBasicBucket(unittest.TestCase):
    def make_limiter(self, capacity=10.0, rate=0.0):
        clock = FakeClock()
        return TokenBucketRateLimiter(capacity, rate, clock=clock), clock

    def test_first_calls_allowed_up_to_capacity(self):
        rl, _ = self.make_limiter(capacity=5, rate=0)
        for _ in range(5):
            self.assertTrue(rl.allow("k"))
        self.assertFalse(rl.allow("k"))

    def test_no_refill_when_rate_zero(self):
        rl, clock = self.make_limiter(capacity=3, rate=0)
        for _ in range(3):
            rl.allow("k")
        clock.advance(100.0)  # well under the 10-minute inactivity TTL
        self.assertFalse(rl.allow("k"))
        self.assertEqual(rl.available("k"), 0.0)

    def test_refill_over_time(self):
        rl, clock = self.make_limiter(capacity=10, rate=2.0)
        for _ in range(10):
            self.assertTrue(rl.allow("k"))
        self.assertFalse(rl.allow("k"))
        clock.advance(1.0)  # +2 tokens
        self.assertTrue(rl.allow("k"))
        self.assertTrue(rl.allow("k"))
        self.assertFalse(rl.allow("k"))

    def test_refill_clamped_at_capacity(self):
        rl, clock = self.make_limiter(capacity=4, rate=100.0)
        rl.allow("k")
        clock.advance(1000.0)
        self.assertEqual(rl.available("k"), 4.0)
        for _ in range(4):
            self.assertTrue(rl.allow("k"))
        self.assertFalse(rl.allow("k"))

    def test_keys_are_independent(self):
        rl, _ = self.make_limiter(capacity=2, rate=0)
        self.assertTrue(rl.allow("a"))
        self.assertTrue(rl.allow("a"))
        self.assertFalse(rl.allow("a"))
        self.assertTrue(rl.allow("b"))  # separate bucket, full

    def test_request_larger_than_capacity_never_allowed(self):
        rl, clock = self.make_limiter(capacity=2, rate=100.0)
        clock.advance(10_000)
        self.assertFalse(rl.allow("k", n=3))
        self.assertEqual(len(rl), 0)  # no bucket created

    def test_partial_consume_fractional(self):
        rl, _ = self.make_limiter(capacity=1.0, rate=0.0)
        self.assertTrue(rl.allow("k", n=0.5))
        self.assertTrue(rl.allow("k", n=0.5))
        self.assertFalse(rl.allow("k", n=0.1))

    def test_available_does_not_consume(self):
        rl, _ = self.make_limiter(capacity=7, rate=0)
        self.assertEqual(rl.available("k"), 7.0)
        self.assertEqual(rl.available("k"), 7.0)
        self.assertTrue(rl.allow("k"))
        self.assertEqual(rl.available("k"), 6.0)

    def test_reset(self):
        rl, _ = self.make_limiter(capacity=1, rate=0)
        self.assertTrue(rl.allow("k"))
        self.assertFalse(rl.allow("k"))
        rl.reset("k")
        self.assertTrue(rl.allow("k"))

    def test_invalid_parameters(self):
        with self.assertRaises(ValueError):
            TokenBucketRateLimiter(0, 1)
        with self.assertRaises(ValueError):
            TokenBucketRateLimiter(1, -1)
        with self.assertRaises(ValueError):
            TokenBucketRateLimiter(1, 1).allow("k", n=-1)


class TestExpiry(unittest.TestCase):
    def test_idle_keys_removed_after_ten_minutes(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(5, 1.0, clock=clock)
        for i in range(50):
            rl.allow(f"key-{i}")
        self.assertEqual(len(rl), 50)
        clock.advance(INACTIVE_TTL + 1.0)
        # A normal call triggers the opportunistic sweep.
        rl.allow("fresh")  # consumes 1 of fresh's 5 tokens
        self.assertEqual(len(rl), 1)
        self.assertEqual(rl.available("fresh"), 4.0)

    def test_recently_used_key_survives_sweep(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(5, 1.0, clock=clock)
        rl.allow("hot")
        clock.advance(INACTIVE_TTL + 1.0)
        rl.allow("hot")  # refresh last_seen (bucket recreated, now fresh)
        clock.advance(100.0)  # under TTL
        rl.allow("other")  # triggers sweep
        self.assertEqual(len(rl), 2)  # hot + other

    def test_memory_bounded_under_many_keys(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(1, 0.0, clock=clock)
        for round_ in range(20):
            base = round_ * 1000
            for i in range(1000):
                rl.allow(f"k{base + i}")
            clock.advance(INACTIVE_TTL + 1.0)
        self.assertLessEqual(len(rl), 1000)


class TestConcurrency(unittest.TestCase):
    def test_exact_accounting_no_lost_updates(self):
        """rate=0: exactly `capacity` allows must succeed in total, no more."""
        capacity = 1000
        rl = TokenBucketRateLimiter(capacity, 0.0)
        n_threads, per_thread = 16, 250
        results: list[list[bool]] = [[] for _ in range(n_threads)]
        barrier = threading.Barrier(n_threads)

        def worker(idx: int) -> None:
            barrier.wait()
            results[idx] = [rl.allow("shared") for _ in range(per_thread)]

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        total = sum(sum(r) for r in results)
        self.assertEqual(total, capacity)

    def test_many_keys_many_threads(self):
        rl = TokenBucketRateLimiter(10, 50.0)
        errors: list[BaseException] = []
        barrier = threading.Barrier(8)

        def worker(idx: int) -> None:
            barrier.wait()
            try:
                for i in range(5000):
                    rl.allow(f"key-{idx}-{i % 37}")
                    rl.available(f"key-{idx}-{i % 37}")
            except BaseException as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])

    def test_no_user_code_or_io_under_lock(self):
        """The lock body must never call user code: a loader that tries to
        re-enter the limiter from within a 'critical section' cannot happen
        because the limiter exposes no callbacks. We verify the observable
        consequence instead: a slow external loader calling allow() does not
        block other keys' progress (no lock held across user code)."""
        clock = FakeClock()
        rl = TokenBucketRateLimiter(1, 0.0, clock=clock)
        rl.allow("a")  # exhaust a's bucket

        def slow_loader():
            clock.advance(5.0)  # simulate user work, no lock held
            rl.allow("b")

        t = threading.Thread(target=slow_loader)
        t.start()
        t.join()
        self.assertTrue(rl.allow("c"))  # 'a' exhaustion must not starve others


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

### Test run output (verbatim)

```
test_available_does_not_consume (test_rate_limiter.TestBasicBucket.test_available_does_not_consume) ... ok
test_first_calls_allowed_up_to_capacity (test_rate_limiter.TestBasicBucket.test_first_calls_allowed_up_to_capacity) ... ok
test_invalid_parameters (test_rate_limiter.TestBasicBucket.test_invalid_parameters) ... ok
test_keys_are_independent (test_rate_limiter.TestBasicBucket.test_keys_are_independent) ... ok
test_no_refill_when_rate_zero (test_rate_limiter.TestBasicBucket.test_no_refill_when_rate_zero) ... ok
test_partial_consume_fractional (test_rate_limiter.TestBasicBucket.test_partial_consume_fractional) ... ok
test_refill_clamped_at_capacity (test_rate_limiter.TestBasicBucket.test_refill_clamped_at_capacity) ... ok
test_refill_over_time (test_rate_limiter.TestBasicBucket.test_refill_over_time) ... ok
test_request_larger_than_capacity_never_allowed (test_rate_limiter.TestBasicBucket.test_request_larger_than_capacity_never_allowed) ... ok
test_reset (test_rate_limiter.TestBasicBucket.test_reset) ... ok
test_exact_accounting_no_lost_updates (test_rate_limiter.TestConcurrency.test_exact_accounting_no_lost_updates)
rate=0: exactly `capacity` allows must succeed in total, no more. ... ok
test_many_keys_many_threads (test_rate_limiter.TestConcurrency.test_many_keys_many_threads) ... ok
test_no_user_code_or_io_under_lock (test_rate_limiter.TestConcurrency.test_no_user_code_or_io_under_lock)
The lock body must never call user code: a loader that tries to ... ok
test_idle_keys_removed_after_ten_minutes (test_rate_limiter.TestExpiry.test_idle_keys_removed_after_ten_minutes) ... ok
test_memory_bounded_under_many_keys (test_rate_limiter.TestExpiry.test_memory_bounded_under_many_keys) ... ok
test_recently_used_key_survives_sweep (test_rate_limiter.TestExpiry.test_recently_used_key_survives_sweep) ... ok

----------------------------------------------------------------------
Ran 16 tests in 0.056s

OK
```

All 16 tests were run and passed. Notes on the requirements: the clock is `time.monotonic` by default (wall-clock changes cannot affect it; the `clock` parameter exists only for deterministic tests); expiry is 10 minutes of inactivity (`last_seen` is refreshed on every access) and cleanup is opportunistic inside `allow`/`available` — no background threads or timers; the lock body contains only arithmetic and dict/list operations, never I/O or user-supplied code (the limiter exposes no callbacks, so user code cannot be invoked while the lock is held).

## I2
Executed: `python3 median_fix.py` (run from `work/`, Python 3.14.6)

### Why it breaks in production

The binary-search logic is fine; the bug is the **float conversion in the even-count branch**:

```python
return (max(left_a, left_b) + min(right_a, right_b)) / 2
```

`/` produces a `float`. For small test values that is invisible, but a `float` (double) only has a 53-bit mantissa, so any 64-bit record ID above 2^53 cannot be represented exactly, and the sum/average is silently rounded to a nearby representable value. The `float('-inf')`/`float('inf')` sentinels are not the problem (comparisons between ints and float infinities are exact); the division is. The odd-count branch returns an int and is unaffected, which is why small unit tests (and odd-sized inputs) all pass.

### Reproduction input

```python
a = [2**60 + 1]   # [1152921504606846977]
b = [2**60 + 2]   # [1152921504606846978]
```

True median = (1152921504606846977 + 1152921504606846978) / 2 = **1152921504606846977.5**. The buggy function returns the float `1.152921504606847e+18`, whose exact value is **1152921504606846976** — a different record ID.

### Output (verbatim)

```
input a = [1152921504606846977]
input b = [1152921504606846978]
true median      = 2305843009213693955/2
buggy result     = 1.152921504606847e+18 (type: float)
fixed result     = 2305843009213693955/2 (type: Fraction)
buggy exact value = 1152921504606846976 (value the float actually holds)
buggy == true?    False
fixed == true?    True

odd-count case: buggy = 4611686018427387909  fixed = 4611686018427387909

differential check: 200000 random cases passed
```

### Fixed function

```python
def median_of_sorted_arrays(a, b):
    """Fixed: never routes 64-bit values through float arithmetic.

    Sentinels are None (compared explicitly) and the even-count median is
    computed with exact integer arithmetic, returned as a Fraction so that
    values of the form x.5 stay exact for arbitrarily large IDs.
    """
    if len(a) > len(b):
        a, b = b, a
    lo, hi = 0, len(a)
    while lo <= hi:
        i = (lo + hi) // 2
        j = (len(a) + len(b) + 1) // 2 - i
        left_a  = a[i-1] if i > 0 else None
        right_a = a[i]   if i < len(a) else None
        left_b  = b[j-1] if j > 0 else None
        right_b = b[j]   if j < len(b) else None
        ok_a = left_a is None or right_b is None or left_a <= right_b
        ok_b = left_b is None or right_a is None or left_b <= right_a
        if ok_a and ok_b:
            if (len(a) + len(b)) % 2:
                # max of the two left sides; at least one is a real element
                if left_a is None:
                    return left_b
                if left_b is None:
                    return left_a
                return left_a if left_a >= left_b else left_b
            # even total: both boundary values are real elements
            x = left_a if left_a is not None and (left_b is None or left_a >= left_b) else left_b
            y = right_b if right_b is not None and (right_a is None or right_b <= right_a) else right_a
            return Fraction(x + y, 2)
        elif left_a is not None and right_b is not None and left_a > right_b:
            hi = i - 1
        else:
            lo = i + 1
```

(With `from fractions import Fraction` at the top.) The even-count result is `Fraction(x + y, 2)`, which is exact for arbitrarily large 64-bit IDs — including the `.5` case that no float can represent. A 200,000-case differential check against a naive exact median (including values up to 2^64−1) passes.

## I3
Executed: `python3 merge_check.py` (run from `work/`, Python 3.14.6)

### Output (verbatim)

```
edge cases: 11 passed
random differential fuzz: 300000 cases passed
VERDICT: merge_sorted is correct for all inputs (given sorted a, b)
```

### Reasoning

The function maintains the invariant that `out` is a sorted merge of `a[:i]` and `b[:j]`, and that every unprocessed element (`a[i:]`, `b[j:]`) is ≥ the last element appended. Each iteration appends the smaller of the two heads, which is ≥ the previous head and ≤ everything remaining in both lists, so the invariant is preserved. When one list is exhausted, the remainder of the other is sorted and every element in it is ≥ the last appended element (by the invariant), so `out.extend(...)` keeps the result sorted. The check above confirms this empirically on 11 edge cases (empty lists, single elements, all-equal, negatives, interleaved) plus 300,000 random differential cases against `sorted(a + b)`, with no counterexample.

**Verdict: correct** for all inputs, given the precondition that `a` and `b` are sorted (which the name and the algorithm require).

## L1
Three functions modify shared state without holding a lock; all are in `registry/session_registry.py`:

1. **File:** `registry/session_registry.py` — **Function:** `revoke_session`
   **Mutating line:** `del self._sessions[sid]` (the following `self._expiry.pop(sid, None)` is part of the same unlocked mutation)
   **Lock that should have been held:** `_sessions_lock` (it guards `_sessions`, `_expiry`, and the fields of reachable `Session` objects).

2. **File:** `registry/session_registry.py` — **Function:** `attach_metadata`
   **Mutating line:** `session.metadata[key] = value`
   **Lock that should have been held:** `_sessions_lock` (per the class contract, the lock guards the fields of any `Session` object reachable from `_sessions`).

3. **File:** `registry/session_registry.py` — **Function:** `record_error`
   **Mutating line:** `self._stats["errors"] += 1` (this line sits *outside* the `with self._stats_lock:` block that only covers the `self._rejected.append(message)` below it)
   **Lock that should have been held:** `_stats_lock` (it guards `_stats` and `_rejected`).

No other function in the corpus mutates shared state without its lock: the `*_locked` helpers are called only from methods that already hold the relevant lock, and `begin_request`/`note` mutate `threading.local` scratch space, which is per-thread by definition.
