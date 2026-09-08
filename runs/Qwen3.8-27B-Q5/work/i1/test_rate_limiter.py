import threading
import time
import unittest

from rate_limiter import RateLimiter


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TokenBucketTests(unittest.TestCase):
    def test_burst_then_denied(self):
        rl = RateLimiter(capacity=2, rate=0.0, clock=lambda: 0.0)
        self.assertTrue(rl.allow("k"))
        self.assertTrue(rl.allow("k"))
        self.assertFalse(rl.allow("k"))

    def test_refill_over_time(self):
        clock = FakeClock()
        rl = RateLimiter(capacity=1, rate=10.0, clock=clock)
        self.assertTrue(rl.allow("k"))
        self.assertFalse(rl.allow("k"))
        clock.advance(0.1)  # +1 token at 10 tokens/sec
        self.assertTrue(rl.allow("k"))
        self.assertFalse(rl.allow("k"))

    def test_tokens_capped_at_capacity(self):
        clock = FakeClock()
        rl = RateLimiter(capacity=5, rate=100.0, clock=clock)
        self.assertTrue(rl.allow("k"))  # drain to 4
        clock.advance(1000)
        self.assertEqual(rl.remaining("k"), 5)

    def test_keys_are_independent(self):
        rl = RateLimiter(capacity=1, rate=0.0, clock=lambda: 0.0)
        self.assertTrue(rl.allow("a"))
        self.assertTrue(rl.allow("b"))
        self.assertFalse(rl.allow("a"))
        self.assertFalse(rl.allow("b"))

    def test_partial_tokens(self):
        rl = RateLimiter(capacity=10, rate=0.0, clock=lambda: 0.0)
        self.assertTrue(rl.allow("k", 4))
        self.assertTrue(rl.allow("k", 4))
        self.assertFalse(rl.allow("k", 3))
        self.assertTrue(rl.allow("k", 2))

    def test_request_larger_than_capacity_denied(self):
        rl = RateLimiter(capacity=5, rate=1.0, clock=lambda: 0.0)
        self.assertFalse(rl.allow("k", 6))

    def test_expired_key_dropped_and_recreated_full(self):
        clock = FakeClock()
        rl = RateLimiter(capacity=2, rate=0.0, expiry=600.0, clock=clock)
        self.assertTrue(rl.allow("k"))
        self.assertTrue(rl.allow("k"))
        self.assertFalse(rl.allow("k"))
        self.assertEqual(rl.active_keys(), 1)
        clock.advance(601)
        # Next call sweeps the expired key and starts a fresh full bucket.
        self.assertTrue(rl.allow("k"))
        self.assertTrue(rl.allow("k"))
        self.assertFalse(rl.allow("k"))

    def test_activity_resets_expiry(self):
        clock = FakeClock()
        rl = RateLimiter(capacity=10, rate=0.0, expiry=600.0, clock=clock)
        rl.allow("k")
        clock.advance(599)
        rl.allow("k")  # activity at t=1599; expiry now t=2199
        clock.advance(599)  # t=2198, still active
        self.assertEqual(rl.active_keys(), 1)
        clock.advance(2)  # t=2200 > 2199
        self.assertEqual(rl.active_keys(), 0)

    def test_backwards_clock_does_not_break(self):
        clock = FakeClock()
        rl = RateLimiter(capacity=1, rate=10.0, clock=clock)
        self.assertTrue(rl.allow("k"))
        clock.advance(-100)  # clock jumps backwards
        self.assertFalse(rl.allow("k"))  # no spurious refill
        clock.advance(200)
        self.assertTrue(rl.allow("k"))

    def test_thread_safety_exact_budget(self):
        rl = RateLimiter(capacity=100, rate=0.0, clock=lambda: 0.0)
        granted = []
        lock = threading.Lock()

        def worker() -> None:
            local = 0
            for _ in range(50):
                if rl.allow("shared"):
                    local += 1
            with lock:
                granted.append(local)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sum(granted), 100)

    def test_thread_safety_mixed_keys(self):
        rl = RateLimiter(capacity=10, rate=50.0, clock=time.monotonic)
        errors: list[BaseException] = []

        def worker(n: int) -> None:
            try:
                for i in range(200):
                    rl.allow(f"key-{n % 7}", 1.0)
                    rl.remaining(f"key-{n % 7}")
            except BaseException as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
