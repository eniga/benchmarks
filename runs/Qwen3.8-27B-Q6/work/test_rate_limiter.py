"""Tests for rate_limiter.TokenBucketRateLimiter (unittest, no deps)."""

import threading
import unittest

from rate_limiter import TokenBucketRateLimiter


class FakeClock:
    """Deterministic, manually advanced clock."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class RateLimiterTests(unittest.TestCase):
    def test_capacity_enforced(self):
        rl = TokenBucketRateLimiter(capacity=5, refill_rate=0, clock=FakeClock())
        for _ in range(5):
            self.assertTrue(rl.allow("k"))
        self.assertFalse(rl.allow("k"))

    def test_refill_over_time(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(capacity=5, refill_rate=1.0, clock=clock)
        for _ in range(5):
            rl.allow("k")
        clock.advance(0.5)
        self.assertFalse(rl.allow("k"))  # only 0.5 tokens refilled
        clock.advance(5.0)  # 5.5s total -> refilled back to capacity
        for _ in range(5):
            self.assertTrue(rl.allow("k"))
        self.assertFalse(rl.allow("k"))

    def test_partial_refill(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(capacity=10, refill_rate=2.0, clock=clock)
        self.assertTrue(rl.allow("k", 10))
        clock.advance(2.0)  # +4 tokens
        self.assertTrue(rl.allow("k", 4))
        self.assertFalse(rl.allow("k", 1))
        self.assertAlmostEqual(rl.remaining("k"), 0.0, places=9)

    def test_per_key_independence(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(capacity=2, refill_rate=0, clock=clock)
        self.assertTrue(rl.allow("a"))
        self.assertTrue(rl.allow("a"))
        self.assertFalse(rl.allow("a"))
        self.assertTrue(rl.allow("b"))
        self.assertTrue(rl.allow("b"))
        self.assertFalse(rl.allow("b"))

    def test_key_expires_after_10_minutes(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(
            capacity=1, refill_rate=0, clock=clock,
            expiry=600.0, cleanup_interval=30.0,
        )
        rl.allow("idle")
        clock.advance(601.0)
        rl.allow("other")  # this call triggers the expiry scan
        self.assertEqual(len(rl), 1)  # "idle" evicted, "other" live
        # the evicted key starts fresh at full capacity
        self.assertTrue(rl.allow("idle"))
        self.assertFalse(rl.allow("idle"))

    def test_recently_used_key_not_evicted(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(
            capacity=1, refill_rate=0, clock=clock,
            expiry=600.0, cleanup_interval=30.0,
        )
        rl.allow("busy")
        clock.advance(599.0)
        self.assertFalse(rl.allow("busy"))  # denied, but still activity
        clock.advance(2.0)
        rl.allow("other")
        self.assertEqual(len(rl), 2)  # "busy" was touched 2s ago

    def test_thread_safety_exact_capacity(self):
        rl = TokenBucketRateLimiter(capacity=1000, refill_rate=0, clock=FakeClock())
        errors: list[BaseException] = []
        allowed = [0] * 8
        tally = threading.Lock()

        def worker(idx: int) -> None:
            local = 0
            try:
                for _ in range(2000):
                    if rl.allow("shared"):
                        local += 1
            except BaseException as exc:  # noqa: BLE001 - report any failure
                errors.append(exc)
            with tally:
                allowed[idx] = local

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(sum(allowed), 1000)  # exactly capacity, no over-allow

    def test_no_background_threads(self):
        before = threading.active_count()
        clock = FakeClock()
        rl = TokenBucketRateLimiter(capacity=10, refill_rate=1.0, clock=clock)
        for i in range(50):
            rl.allow(f"k{i % 3}")
            clock.advance(1.0)
        self.assertEqual(threading.active_count(), before)

    def test_backward_clock_jump_is_safe(self):
        clock = FakeClock(start=100.0)
        rl = TokenBucketRateLimiter(capacity=10, refill_rate=10.0, clock=clock)
        self.assertTrue(rl.allow("k", 10))
        clock.now = 50.0  # clock jumps backward
        self.assertFalse(rl.allow("k"))  # no refill, no crash
        self.assertAlmostEqual(rl.remaining("k"), 0.0, places=9)
        clock.now = 101.0  # forward again: 1s * 10/s = 10 tokens (capped)
        self.assertTrue(rl.allow("k", 10))

    def test_clock_never_called_under_lock(self):
        """Invariant: no user-supplied code runs while the lock is held."""
        clock = FakeClock()
        calls_held: list[bool] = []
        rl = TokenBucketRateLimiter(capacity=3, refill_rate=1.0, clock=clock)

        def spy_clock() -> float:
            free = rl._lock.acquire(blocking=False)
            if free:
                rl._lock.release()
            calls_held.append(not free)
            return clock()

        rl._clock = spy_clock  # swap in after construction
        for i in range(20):
            rl.allow(f"k{i % 2}")
            rl.remaining(f"k{i % 2}")
            clock.advance(1.0)
        self.assertTrue(calls_held)
        self.assertTrue(all(h is False for h in calls_held),
                        "clock was invoked while the limiter lock was held")

    def test_invalid_parameters(self):
        with self.assertRaises(ValueError):
            TokenBucketRateLimiter(capacity=0, refill_rate=1.0)
        with self.assertRaises(ValueError):
            TokenBucketRateLimiter(capacity=1.0, refill_rate=-1.0)
        with self.assertRaises(ValueError):
            TokenBucketRateLimiter(capacity=1.0, refill_rate=1.0, expiry=0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
