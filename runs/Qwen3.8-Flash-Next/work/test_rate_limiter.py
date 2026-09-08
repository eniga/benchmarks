"""Tests for rate_limiter.TokenBucketRateLimiter (stdlib unittest only)."""

import threading
import time
import unittest

from rate_limiter import DEFAULT_IDLE_TTL, TokenBucketRateLimiter


class FakeClock:
    """Deterministic stand-in for time.monotonic."""

    def __init__(self, start=1_000.0):
        self.t = float(start)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.t

    def advance(self, seconds):
        self.t += float(seconds)


class LockProbeClock(FakeClock):
    """Clock that fails loudly if it is ever called while the lock is held."""

    def __init__(self, limiter, start=1_000.0):
        super().__init__(start)
        self.limiter = limiter

    def __call__(self):
        probe = self.limiter._lock.acquire(blocking=False)
        try:
            assert probe, "clock callback ran while the limiter lock was held"
        finally:
            if probe:
                self.limiter._lock.release()
        return super().__call__()


class BasicTests(unittest.TestCase):
    def test_capacity_is_the_burst_size(self):
        rl = TokenBucketRateLimiter(capacity=5, refill_rate=1, clock=FakeClock())
        self.assertEqual([rl.acquire("a") for _ in range(6)], [True] * 5 + [False])

    def test_keys_are_independent(self):
        rl = TokenBucketRateLimiter(capacity=1, refill_rate=0, clock=FakeClock())
        self.assertTrue(rl.acquire("a"))
        self.assertFalse(rl.acquire("a"))
        self.assertTrue(rl.acquire("b"))

    def test_refill_is_capped_at_capacity(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(capacity=3, refill_rate=10, clock=clock)
        for _ in range(3):
            self.assertTrue(rl.acquire("a"))
        clock.advance(10)  # would be 100 tokens uncapped
        self.assertEqual(rl.available("a"), 3)
        self.assertEqual([rl.acquire("a", 1) for _ in range(4)], [True] * 3 + [False])

    def test_refill_rate(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(capacity=1, refill_rate=2, clock=clock)
        self.assertTrue(rl.acquire("a"))
        self.assertFalse(rl.acquire("a"))
        clock.advance(0.25)  # half a token
        self.assertFalse(rl.acquire("a"))
        clock.advance(0.25)  # now there is a whole token
        self.assertTrue(rl.acquire("a"))

    def test_burst_of_several_tokens(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(capacity=10, refill_rate=1, clock=clock)
        self.assertTrue(rl.acquire("a", 10))
        self.assertFalse(rl.acquire("a", 1))
        clock.advance(1)  # exactly one token back
        self.assertTrue(rl.acquire("a", 1))
        self.assertFalse(rl.acquire("a", 1))

    def test_zero_refill_rate_never_refills(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(capacity=1, refill_rate=0, idle_ttl=600, clock=clock)
        self.assertTrue(rl.acquire("a"))
        clock.advance(599)  # still inside the idle window, so the bucket survives
        self.assertEqual(rl.size(), 1)
        self.assertFalse(rl.acquire("a"))
        self.assertEqual(rl.wait_time("a"), float("inf"))

    def test_wait_time(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(capacity=2, refill_rate=4, clock=clock)
        self.assertEqual(rl.wait_time("a"), 0.0)
        self.assertTrue(rl.acquire("a", 2))
        self.assertAlmostEqual(rl.wait_time("a"), 0.25)

    def test_check_does_not_consume_or_keep_alive(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(capacity=2, refill_rate=0, idle_ttl=100, clock=clock)
        self.assertTrue(rl.acquire("a"))
        self.assertTrue(rl.check("a"))
        self.assertTrue(rl.check("a"))
        self.assertAlmostEqual(rl.available("a"), 1)
        clock.advance(150)
        self.assertEqual(rl.sweep(), 1)  # peeking did not keep "a" alive

    def test_argument_validation(self):
        for bad in (dict(capacity=0, refill_rate=1), dict(capacity=-1, refill_rate=1),
                    dict(capacity=1, refill_rate=-1), dict(capacity=1, refill_rate=1, idle_ttl=0)):
            with self.assertRaises(ValueError):
                TokenBucketRateLimiter(**bad)
        rl = TokenBucketRateLimiter(capacity=1, refill_rate=1, clock=FakeClock())
        with self.assertRaises(ValueError):
            rl.acquire("a", 0)
        with self.assertRaises(ValueError):
            rl.acquire("a", -2)


class ExpiryTests(unittest.TestCase):
    def test_default_ttl_is_ten_minutes(self):
        self.assertEqual(DEFAULT_IDLE_TTL, 600.0)
        rl = TokenBucketRateLimiter(capacity=1, refill_rate=1)
        self.assertEqual(rl._idle_ttl, 600.0)

    def test_idle_keys_are_dropped_during_normal_calls(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(capacity=5, refill_rate=1, idle_ttl=600, clock=clock)
        for i in range(50):
            rl.acquire(f"key-{i}")
        self.assertEqual(rl.size(), 50)
        clock.advance(601)
        rl.acquire("fresh")
        self.assertEqual(rl.size(), 1)          # the 50 idle keys are gone
        self.assertEqual(rl.available("key-0"), 5)  # forgotten, not resurrected

    def test_key_used_within_ttl_survives(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(capacity=5, refill_rate=0, idle_ttl=600, clock=clock)
        rl.acquire("a")
        clock.advance(599)
        rl.acquire("b")
        clock.advance(599)  # "a" is now 1198s idle, "b" 599s idle
        self.assertTrue(rl.acquire("c"))
        self.assertEqual(rl.size(), 2)
        self.assertEqual(rl.available("b"), 4)

    def test_reset_and_clear(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(capacity=2, refill_rate=0, clock=clock)
        rl.acquire("a")
        self.assertEqual(rl.size(), 1)
        self.assertTrue(rl.reset("a"))
        self.assertFalse(rl.reset("a"))
        rl.acquire("a")
        rl.acquire("b")
        rl.clear()
        self.assertEqual(rl.size(), 0)


class ClockTests(unittest.TestCase):
    def test_uses_monotonic_clock_by_default(self):
        rl = TokenBucketRateLimiter(capacity=1, refill_rate=1)
        self.assertIs(rl._clock, time.monotonic)

    def test_clock_is_never_called_with_the_lock_held(self):
        clock = LockProbeClock(TokenBucketRateLimiter(capacity=1, refill_rate=1))
        rl = TokenBucketRateLimiter(capacity=10, refill_rate=1, clock=clock)
        clock.limiter = rl
        for key in ("a", "b", "c"):
            rl.acquire(key)
            rl.check(key)
            rl.available(key)
            rl.wait_time(key)
            rl.reset(key)
        rl.sweep()
        self.assertGreater(clock.calls, 0)

    def test_clock_going_backwards_does_not_grant_tokens(self):
        clock = FakeClock(start=10_000.0)
        rl = TokenBucketRateLimiter(capacity=3, refill_rate=1000, clock=clock)
        self.assertEqual([rl.acquire("a") for _ in range(3)], [True] * 3)
        clock.advance(-30)  # simulated backwards clock jump
        self.assertFalse(rl.acquire("a"))            # no free tokens from the jump
        self.assertEqual(rl.available("a"), 0)       # and none from the peek
        clock.advance(31)                            # back to the original instant, +1s
        self.assertTrue(rl.acquire("a"))
        self.assertEqual(rl.available("a"), 2)


class ThreadingTests(unittest.TestCase):
    def test_no_extra_threads_are_created(self):
        before = threading.enumerate()
        rl = TokenBucketRateLimiter(capacity=1, refill_rate=1)
        rl.acquire("a")
        rl.acquire("a")
        self.assertEqual(threading.enumerate(), before)

    def test_exact_grant_under_concurrency(self):
        rl = TokenBucketRateLimiter(capacity=100, refill_rate=0)
        results = []
        lock = threading.Lock()

        def worker():
            local = sum(1 for _ in range(1000) if rl.acquire("shared"))
            with lock:
                results.append(local)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sum(results), 100)
        self.assertEqual(rl.available("shared"), 0)

    def test_concurrent_multi_key_churn_stays_consistent(self):
        rl = TokenBucketRateLimiter(capacity=4, refill_rate=0.5, idle_ttl=0.05)
        errors = []

        def worker(seed):
            try:
                deadline = time.monotonic() + 0.30
                while time.monotonic() < deadline:
                    key = f"k{(seed + len(str(seed))) % 7}"
                    rl.acquire(key)
                    rl.available(key)
                    rl.check(key)
                    self.assertLessEqual(rl.size(), 4096)
                    time.sleep(0.001)
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        # idle_ttl is short and these keys are old by now: a sweep must shrink us
        time.sleep(0.06)
        rl.sweep()
        self.assertEqual(rl.size(), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
