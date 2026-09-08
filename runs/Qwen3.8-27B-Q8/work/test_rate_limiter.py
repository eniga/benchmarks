"""Tests for rate_limiter.TokenBucketRateLimiter."""

import threading
import time
import unittest

from rate_limiter import TokenBucketRateLimiter


class FakeClock:
    """Deterministic monotonic clock for tests."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def jump(self, seconds: float) -> None:
        """May be negative; a real monotonic clock would never do this."""
        self.now += seconds


class AllowTests(unittest.TestCase):
    def test_burst_then_deny(self):
        rl = TokenBucketRateLimiter(capacity=5, refill_rate=0.0)
        results = [rl.allow("k") for _ in range(7)]
        self.assertEqual(results, [True] * 5 + [False, False])

    def test_refill_over_time(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(capacity=10, refill_rate=10.0, clock=clock)
        for _ in range(10):
            self.assertTrue(rl.allow("k"))
        self.assertFalse(rl.allow("k"))
        clock.advance(0.5)  # refills 5 tokens
        for _ in range(5):
            self.assertTrue(rl.allow("k"))
        self.assertFalse(rl.allow("k"))

    def test_refill_capped_at_capacity(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(capacity=5, refill_rate=100.0, clock=clock)
        rl.allow("k")
        clock.advance(100.0)  # would add 10000 tokens
        granted = sum(rl.allow("k") for _ in range(10))
        self.assertEqual(granted, 5)  # capped at capacity

    def test_per_key_isolation(self):
        rl = TokenBucketRateLimiter(capacity=2, refill_rate=0.0)
        self.assertTrue(rl.allow("a"))
        self.assertTrue(rl.allow("a"))
        self.assertFalse(rl.allow("a"))
        self.assertTrue(rl.allow("b"))  # independent bucket

    def test_multi_token_requests(self):
        rl = TokenBucketRateLimiter(capacity=10, refill_rate=0.0)
        self.assertTrue(rl.allow("k", 4))
        self.assertTrue(rl.allow("k", 4))
        self.assertFalse(rl.allow("k", 3))
        self.assertFalse(rl.allow("k", 11))  # exceeds capacity, always denied

    def test_zero_token_request_granted(self):
        rl = TokenBucketRateLimiter(capacity=1, refill_rate=0.0)
        self.assertTrue(rl.allow("k", 0))
        self.assertTrue(rl.allow("k", 0))

    def test_invalid_arguments(self):
        with self.assertRaises(ValueError):
            TokenBucketRateLimiter(capacity=0, refill_rate=1.0)
        with self.assertRaises(ValueError):
            TokenBucketRateLimiter(capacity=1, refill_rate=-1.0)
        rl = TokenBucketRateLimiter(capacity=1, refill_rate=1.0)
        with self.assertRaises(ValueError):
            rl.allow("k", -1)


class ExpiryTests(unittest.TestCase):
    def test_inactive_key_removed_by_ordinary_call(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(
            capacity=5, refill_rate=0.0, expiry=600.0,
            cleanup_interval=1.0, clock=clock,
        )
        rl.allow("k")
        self.assertEqual(rl.size(), 1)
        clock.advance(601.0)
        rl.allow("other")  # ordinary call triggers the sweep
        self.assertEqual(rl.size(), 1)  # only "other" remains
        self.assertTrue(rl.allow("other"))

    def test_expired_key_starts_fresh(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(
            capacity=5, refill_rate=0.0, expiry=600.0,
            cleanup_interval=1.0, clock=clock,
        )
        rl.allow("k")
        clock.advance(601.0)
        rl.allow("other")  # sweep removes "k"
        granted = sum(rl.allow("k") for _ in range(6))
        self.assertEqual(granted, 5)  # fresh, full bucket

    def test_active_key_not_expired(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(
            capacity=100, refill_rate=0.0, expiry=600.0,
            cleanup_interval=1.0, clock=clock,
        )
        for _ in range(10):
            self.assertTrue(rl.allow("k"))
            clock.advance(300.0)  # 5 min gaps, each < 10 min expiry
        self.assertEqual(rl.size(), 1)

    def test_cleanup_is_lazy_not_background(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(
            capacity=1, refill_rate=0.0, expiry=10.0,
            cleanup_interval=1.0, clock=clock,
        )
        rl.allow("k")
        clock.advance(100.0)
        self.assertEqual(rl.size(), 1)  # nothing runs between calls
        rl.allow("x")
        self.assertEqual(rl.size(), 1)  # swept during this call

    def test_sweep_is_rate_limited(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(
            capacity=1, refill_rate=0.0, expiry=10.0,
            cleanup_interval=100.0, clock=clock,
        )
        rl.allow("k")
        self.assertEqual(rl._last_sweep, 1000.0)  # sweep ran on first call
        clock.advance(50.0)
        rl.allow("x")   # only 50s since last sweep: no sweep
        self.assertEqual(rl._last_sweep, 1000.0)  # unchanged
        clock.advance(50.0)
        rl.allow("y")   # 100s since last sweep: sweep runs
        self.assertEqual(rl._last_sweep, 1100.0)


class MonotonicClockTests(unittest.TestCase):
    def test_default_clock_is_time_monotonic(self):
        rl = TokenBucketRateLimiter(capacity=1, refill_rate=1.0)
        self.assertIs(rl._clock, time.monotonic)

    def test_clock_jump_backwards_is_harmless(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(capacity=10, refill_rate=10.0, clock=clock)
        self.assertTrue(rl.allow("k"))
        clock.jump(-1000.0)  # impossible for a real monotonic clock
        self.assertFalse(rl.allow("k", 10))  # no phantom refill
        self.assertTrue(rl.allow("k", 9))    # existing tokens intact


class WaitTimeTests(unittest.TestCase):
    def test_wait_time_values(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(capacity=10, refill_rate=2.0, clock=clock)
        for _ in range(10):
            rl.allow("k")
        self.assertAlmostEqual(rl.wait_time("k", 1.0), 0.5)
        clock.advance(0.5)
        self.assertEqual(rl.wait_time("k", 1.0), 0.0)
        self.assertTrue(rl.allow("k"))

    def test_wait_time_unknown_key_is_zero(self):
        rl = TokenBucketRateLimiter(capacity=10, refill_rate=2.0)
        self.assertEqual(rl.wait_time("never-seen"), 0.0)

    def test_wait_time_never_with_zero_rate(self):
        rl = TokenBucketRateLimiter(capacity=1, refill_rate=0.0)
        rl.allow("k")
        self.assertEqual(rl.wait_time("k", 1.0), float("inf"))

    def test_wait_time_exceeds_capacity(self):
        rl = TokenBucketRateLimiter(capacity=1, refill_rate=1.0)
        self.assertEqual(rl.wait_time("k", 2.0), float("inf"))


class ThreadSafetyTests(unittest.TestCase):
    def test_exact_capacity_granted_under_contention(self):
        rl = TokenBucketRateLimiter(capacity=1000, refill_rate=0.0)
        totals: list[int] = []
        totals_lock = threading.Lock()

        def worker() -> None:
            local = 0
            for _ in range(200):
                if rl.allow("shared"):
                    local += 1
            with totals_lock:
                totals.append(local)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sum(totals), 1000)  # exactly capacity, no more

    def test_mixed_keys_under_contention(self):
        rl = TokenBucketRateLimiter(capacity=100, refill_rate=0.0)
        errors: list[BaseException] = []
        errors_lock = threading.Lock()

        def worker(idx: int) -> None:
            try:
                for _ in range(100):
                    rl.allow(f"key-{idx % 7}")
                    rl.wait_time(f"key-{idx % 7}")
                    rl.size()
            except BaseException as exc:  # noqa: BLE001 - test harness
                with errors_lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(rl.size(), 7)


if __name__ == "__main__":
    unittest.main(verbosity=2)
