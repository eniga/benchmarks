"""Tests for rate_limiter.TokenBucketRateLimiter (plain unittest, no deps)."""

import threading
import unittest
from rate_limiter import TokenBucketRateLimiter


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class BasicBehaviour(unittest.TestCase):
    def test_initial_capacity_then_denied(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(capacity=3, refill_rate=0.0, clock=clock)
        self.assertEqual([rl.consume("k") for _ in range(4)],
                         [True, True, True, False])

    def test_refill_over_time(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(capacity=10, refill_rate=5.0, clock=clock)
        for _ in range(10):
            rl.consume("k")
        self.assertFalse(rl.consume("k"))
        clock.advance(1.0)  # +5 tokens
        self.assertTrue(rl.consume("k"))
        self.assertTrue(rl.consume("k"))
        self.assertTrue(rl.consume("k"))
        self.assertTrue(rl.consume("k"))
        self.assertTrue(rl.consume("k"))
        self.assertFalse(rl.consume("k"))

    def test_refill_capped_at_capacity(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(capacity=10, refill_rate=100.0, clock=clock)
        for _ in range(10):
            rl.consume("k")
        clock.advance(1000.0)
        self.assertEqual(rl.available("k"), 10.0)

    def test_per_key_independence(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(capacity=2, refill_rate=0.0, clock=clock)
        self.assertTrue(rl.consume("a"))
        self.assertTrue(rl.consume("a"))
        self.assertFalse(rl.consume("a"))
        self.assertTrue(rl.consume("b"))  # b unaffected by a's exhaustion

    def test_multi_token_consume(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(capacity=5, refill_rate=0.0, clock=clock)
        self.assertTrue(rl.consume("k", 4))
        self.assertFalse(rl.consume("k", 2))
        self.assertTrue(rl.consume("k", 1))
        self.assertFalse(rl.consume("k", 1))

    def test_request_larger_than_capacity_always_denied(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(capacity=5, refill_rate=100.0, clock=clock)
        clock.advance(1000.0)
        self.assertFalse(rl.consume("k", 6))

    def test_backward_clock_jump_grants_nothing(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(capacity=10, refill_rate=100.0, clock=clock)
        for _ in range(10):
            rl.consume("k")
        clock.advance(-500.0)  # impossible for time.monotonic, but must not break
        self.assertFalse(rl.consume("k"))
        self.assertEqual(rl.available("k"), 0.0)

    def test_fractional_refill(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(capacity=10, refill_rate=1.0, clock=clock)
        for _ in range(10):
            rl.consume("k")
        clock.advance(0.5)
        self.assertFalse(rl.consume("k", 1))
        self.assertAlmostEqual(rl.available("k"), 0.5)


class Expiry(unittest.TestCase):
    def test_idle_key_swept_and_memory_bounded(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(
            capacity=1, refill_rate=0.0, clock=clock,
            idle_ttl=600.0, sweep_threshold=2,
        )
        rl.consume("old")
        clock.advance(601.0)  # "old" now idle for > 10 minutes
        rl.consume("new1")    # table at threshold -> sweep removes "old"
        rl.consume("new2")
        self.assertEqual(len(rl), 2)
        self.assertNotIn("old", rl._buckets)

    def test_recent_key_not_swept(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(
            capacity=1, refill_rate=0.0, clock=clock,
            idle_ttl=600.0, sweep_threshold=2,
        )
        rl.consume("a")
        clock.advance(300.0)
        rl.consume("a")       # activity resets the idle window
        clock.advance(300.0)  # total 600s since first touch, 300s since last
        rl.consume("b")       # triggers sweep; "a" only 300s idle -> kept
        self.assertIn("a", rl._buckets)

    def test_expired_key_gets_fresh_bucket(self):
        clock = FakeClock()
        rl = TokenBucketRateLimiter(
            capacity=5, refill_rate=0.0, clock=clock,
            idle_ttl=600.0, sweep_threshold=1,
        )
        for _ in range(5):
            rl.consume("k")
        self.assertFalse(rl.consume("k"))
        clock.advance(601.0)
        rl.consume("other")   # sweep removes exhausted "k"
        self.assertTrue(rl.consume("k", 5))  # fresh full bucket


class Concurrency(unittest.TestCase):
    def test_no_tokens_lost_under_contention(self):
        rl = TokenBucketRateLimiter(capacity=100, refill_rate=0.0)
        n_threads, per_thread = 8, 5000
        results = []
        lock = threading.Lock()
        barrier = threading.Barrier(n_threads)

        def worker():
            barrier.wait()
            local = 0
            for _ in range(per_thread):
                if rl.consume("hot"):
                    local += 1
            with lock:
                results.append(local)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sum(results), 100)  # exactly capacity, no more, no less

    def test_multi_key_stress_no_errors(self):
        rl = TokenBucketRateLimiter(capacity=10, refill_rate=10.0)
        errors = []

        def worker(tid):
            try:
                for i in range(2000):
                    rl.consume(f"key-{tid % 7}", 1 + (i % 3))
                    rl.available(f"key-{tid % 7}")
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])

    def test_reset_under_contention(self):
        rl = TokenBucketRateLimiter(capacity=10, refill_rate=0.0)
        stop = threading.Event()

        def worker():
            while not stop.is_set():
                rl.consume("k")
                rl.reset("k")

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        import time
        time.sleep(0.2)
        stop.set()
        for t in threads:
            t.join()
        self.assertLessEqual(len(rl), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
