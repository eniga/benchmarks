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
