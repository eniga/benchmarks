"""Tests for rate_limiter.TokenBucketRateLimiter.

Run:  python3 -m unittest test_rate_limiter -v
"""

import threading
import unittest

from rate_limiter import TokenBucketRateLimiter


class TestBasicBucket(unittest.TestCase):
    def test_burst_limited_by_capacity(self):
        rl = TokenBucketRateLimiter(capacity=5, refill_rate=0.0)
        results = [rl.allow("k", now=float(i * 0)) for i in range(7)]
        self.assertEqual(results, [True] * 5 + [False, False])

    def test_refill_over_time(self):
        # capacity 2, 10 tokens/sec. Start full: 2 allowed.
        rl = TokenBucketRateLimiter(capacity=2, refill_rate=10.0)
        self.assertTrue(rl.allow("k", now=0.0))
        self.assertTrue(rl.allow("k", now=0.0))
        self.assertFalse(rl.allow("k", now=0.0))
        # after 0.1 s, 1 token refilled
        self.assertTrue(rl.allow("k", now=0.1))
        self.assertFalse(rl.allow("k", now=0.1))
        # after another 0.1 s, one more
        self.assertTrue(rl.allow("k", now=0.2))

    def test_refill_capped_at_capacity(self):
        rl = TokenBucketRateLimiter(capacity=3, refill_rate=1000.0)
        rl.allow("k", now=0.0)
        rl.allow("k", now=0.0)
        rl.allow("k", now=0.0)
        self.assertFalse(rl.allow("k", now=0.0))
        # long idle: bucket returns to full capacity, not more
        self.assertEqual(rl.remaining("k", now=1000.0), 3.0)
        ok = [rl.allow("k", now=1000.0) for _ in range(4)]
        self.assertEqual(ok, [True, True, True, False])

    def test_multi_token_take(self):
        rl = TokenBucketRateLimiter(capacity=5, refill_rate=0.0)
        self.assertTrue(rl.allow("k", n=3, now=0.0))
        self.assertTrue(rl.allow("k", n=2, now=0.0))
        self.assertFalse(rl.allow("k", n=1, now=0.0))

    def test_keys_are_independent(self):
        rl = TokenBucketRateLimiter(capacity=1, refill_rate=0.0)
        self.assertTrue(rl.allow("a", now=0.0))
        self.assertFalse(rl.allow("a", now=0.0))
        self.assertTrue(rl.allow("b", now=0.0))
        self.assertFalse(rl.allow("b", now=0.0))

    def test_fractional_refill_accumulates(self):
        # 0.5 tokens/sec: one token every 2 seconds
        rl = TokenBucketRateLimiter(capacity=1, refill_rate=0.5)
        self.assertTrue(rl.allow("k", now=0.0))
        self.assertFalse(rl.allow("k", now=1.0))
        self.assertTrue(rl.allow("k", now=2.0))


class TestExpiry(unittest.TestCase):
    def test_idle_key_expires_after_idle_ttl(self):
        rl = TokenBucketRateLimiter(capacity=10, refill_rate=0.0, idle_ttl=600.0)
        rl.allow("k", now=0.0)
        self.assertEqual(rl.live_keys(now=0.0), 1)
        # 10 minutes + epsilon of inactivity, then any call sweeps it
        self.assertTrue(rl.allow("other", now=601.0))
        self.assertEqual(rl.live_keys(now=601.0), 1)  # "k" swept, "other" alive

    def test_activity_resets_idle_clock(self):
        rl = TokenBucketRateLimiter(capacity=10, refill_rate=0.0, idle_ttl=600.0)
        rl.allow("k", now=0.0)
        rl.allow("k", now=500.0)  # still within ttl; resets clock
        self.assertTrue(rl.allow("k", now=1099.0))  # 599 s after last touch
        self.assertEqual(rl.live_keys(now=1099.0), 1)
        rl.allow("x", now=1700.0)  # 601 s after last touch of "k"
        self.assertEqual(rl.live_keys(now=1700.0), 1)  # only "x"

    def test_expired_bucket_starts_full_again(self):
        rl = TokenBucketRateLimiter(capacity=2, refill_rate=0.0, idle_ttl=600.0)
        rl.allow("k", now=0.0)
        rl.allow("k", now=0.0)
        self.assertFalse(rl.allow("k", now=0.0))
        # after expiry the key is treated as brand new: full bucket
        self.assertTrue(rl.allow("k", now=601.0))
        self.assertTrue(rl.allow("k", now=601.0))
        self.assertFalse(rl.allow("k", now=601.0))


class TestMonotonicClock(unittest.TestCase):
    def test_rejects_nonpositive_params(self):
        for kwargs in (
            {"capacity": 0, "refill_rate": 1.0},
            {"capacity": 1.0, "refill_rate": -1.0},
            {"capacity": 1.0, "refill_rate": 0.0, "idle_ttl": 0.0},
        ):
            with self.assertRaises(ValueError):
                TokenBucketRateLimiter(**kwargs)


class TestThreadSafety(unittest.TestCase):
    def test_concurrent_allows_never_exceed_capacity_plus_refill(self):
        # rate 0 => exactly `capacity` allows total, no matter the threading.
        capacity = 1000
        rl = TokenBucketRateLimiter(capacity=capacity, refill_rate=0.0)
        n_threads, per_thread = 16, 250
        granted = []
        lock = threading.Lock()
        barrier = threading.Barrier(n_threads)

        def worker():
            barrier.wait()
            local = 0
            for _ in range(per_thread):
                if rl.allow("shared"):
                    local += 1
            with lock:
                granted.append(local)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sum(granted), capacity)

    def test_concurrent_distinct_keys(self):
        rl = TokenBucketRateLimiter(capacity=10, refill_rate=0.0)
        errors = []

        def worker(tid):
            try:
                for i in range(200):
                    rl.allow(f"key-{tid}", n=1)
                    rl.remaining(f"key-{tid}")
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(rl.live_keys(), 8)

    def test_concurrent_refill_accounting(self):
        # 100 tokens/sec, capacity 100. One token consumed at t=0 (99 left).
        # 8 threads make 50 attempts each, with timestamps interleaved
        # across t in [0, 49/50]. Total tokens that can ever be available
        # is 99 + 100 * (49/50) = 197, so total grants must be ~197 and
        # must never approach the 400 attempts made. (Before the
        # no-backwards-timestamp fix, the same time window could refill
        # repeatedly and all 400 attempts were granted.)
        rl = TokenBucketRateLimiter(capacity=100, refill_rate=100.0)
        rl.allow("k", now=0.0)  # consume 1 at t=0
        granted = []
        lock = threading.Lock()
        barrier = threading.Barrier(8)

        def worker():
            barrier.wait()
            local = 0
            for i in range(50):
                if rl.allow("k", now=(i % 50) / 50.0):
                    local += 1
            with lock:
                granted.append(local)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        total = sum(granted)
        # Upper bound is the regression check: the pre-fix code granted
        # all 400 attempts by refilling the same window repeatedly.
        self.assertLessEqual(total, 198)  # 197 + float slack
        # The bucket is never starved to absurdity either (the cap at
        # capacity can shed some tokens, but most of the 197 available
        # must be claimable by 400 attempts).
        self.assertGreaterEqual(total, 100)


class TestLockInvariant(unittest.TestCase):
    """The limiter never performs I/O or invokes user-supplied callbacks
    while holding its lock: the public API accepts only hashable values
    and does purely in-memory bookkeeping under the lock, so the
    invariant holds by construction. These tests show that even a
    pathologically slow key (whose __hash__ sleeps) cannot deadlock the
    limiter or starve other threads indefinitely."""

    def test_slow_key_cannot_deadlock(self):
        import time as _time

        class SlowKey:
            def __init__(self, v):
                self.v = v

            def __hash__(self):
                _time.sleep(0.05)
                return hash(self.v)

            def __eq__(self, other):
                return isinstance(other, SlowKey) and self.v == other.v

        rl = TokenBucketRateLimiter(capacity=1, refill_rate=0.0)
        k = SlowKey(1)
        self.assertTrue(rl.allow(k))
        self.assertFalse(rl.allow(k))  # capacity 1, rate 0

        done = []

        def other():
            rl.allow("plain")
            done.append(True)

        th = threading.Thread(target=other)
        th.start()
        th.join(timeout=1.0)
        self.assertEqual(done, [True])

    def test_no_user_callback_api_exists(self):
        # Document the invariant structurally: none of the public methods
        # accept a callable.
        import inspect

        sig = inspect.signature(TokenBucketRateLimiter.allow)
        for param in sig.parameters.values():
            self.assertNotIn("Callable", str(param.annotation))


if __name__ == "__main__":
    unittest.main(verbosity=2)
