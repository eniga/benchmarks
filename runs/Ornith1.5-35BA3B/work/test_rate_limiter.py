"""Tests for rate_limiter.RateLimiter.

Run:  python3 -m pytest test_rate_limiter.py -v
   or: python3 test_rate_limiter.py
"""

import threading
import time

from rate_limiter import RateLimiter


class FakeClock:
    """A controllable monotonic-style clock (never goes backward)."""

    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        assert dt >= 0  # monotonic: only ever moves forward
        self.t += dt


# ---------------------------------------------------------------------------
# Basic token-bucket behaviour
# ---------------------------------------------------------------------------
def test_capacity_is_burst_limit():
    clk = FakeClock()
    rl = RateLimiter(capacity=5, refill_rate=1, ttl=600, clock=clk)
    results = [rl.try_acquire("k") for _ in range(5)]
    assert results == [True] * 5
    assert rl.try_acquire("k") is False  # 6th denied until refill


def test_refill_over_time():
    clk = FakeClock()
    rl = RateLimiter(capacity=2, refill_rate=10, ttl=600, clock=clk)
    assert rl.try_acquire("k") is True
    assert rl.try_acquire("k") is True
    assert rl.try_acquire("k") is False
    clk.advance(0.2)  # 0.2 s * 10 = 2 tokens refilled
    assert rl.try_acquire("k") is True
    assert rl.try_acquire("k") is True
    assert rl.try_acquire("k") is False


def test_amount_consumes_multiple_tokens():
    clk = FakeClock()
    rl = RateLimiter(capacity=5, refill_rate=0, ttl=600, clock=clk)
    assert rl.try_acquire("k", amount=3) is True
    assert rl.try_acquire("k", amount=3) is False  # only 2 left
    assert rl.available("k") == 2


def test_per_key_independence():
    clk = FakeClock()
    rl = RateLimiter(capacity=1, refill_rate=0, ttl=600, clock=clk)
    assert rl.try_acquire("a") is True
    assert rl.try_acquire("a") is False
    assert rl.try_acquire("b") is True  # separate bucket


def test_available_reflects_refill():
    clk = FakeClock()
    rl = RateLimiter(capacity=10, refill_rate=5, ttl=600, clock=clk)
    assert rl.available("k") == 10
    rl.try_acquire("k", amount=5)
    assert abs(rl.available("k") - 5) < 1e-9
    clk.advance(1.0)  # +5 tokens
    assert abs(rl.available("k") - 10) < 1e-9


def test_capacity_capped():
    clk = FakeClock()
    rl = RateLimiter(capacity=4, refill_rate=100, ttl=600, clock=clk)
    rl.try_acquire("k")  # consume 1 -> 3 left
    clk.advance(100.0)  # would add 10000 tokens
    assert rl.available("k") == 4  # but capped at capacity


# ---------------------------------------------------------------------------
# Expiry / memory bounding
# ---------------------------------------------------------------------------
def test_idle_key_is_reclaimed():
    clk = FakeClock()
    rl = RateLimiter(capacity=5, refill_rate=0, ttl=10, clock=clk,
                     sweep_interval=1)
    rl.try_acquire("k")
    assert len(rl) == 1
    clk.advance(11)  # past ttl, no further access
    rl.try_acquire("other")  # triggers a cleanup sweep
    assert len(rl) == 1  # "k" was evicted


def test_expired_key_starts_fresh():
    clk = FakeClock()
    rl = RateLimiter(capacity=1, refill_rate=0, ttl=10, clock=clk,
                     sweep_interval=1)
    assert rl.try_acquire("k") is True
    assert rl.try_acquire("k") is False
    clk.advance(11)  # key expires
    assert rl.try_acquire("k") is True  # fresh full bucket


# ---------------------------------------------------------------------------
# Monotonic clock behaviour
# ---------------------------------------------------------------------------
def test_clock_jump_forward_does_not_overrefill():
    clk = FakeClock()
    rl = RateLimiter(capacity=5, refill_rate=1, ttl=600, clock=clk)
    rl.try_acquire("k")
    rl.try_acquire("k")
    clk.advance(1000)  # huge forward jump
    assert rl.available("k") == 5  # capped, not over-refilled


def test_backward_clock_is_safe():
    # The limiter mandates a monotonic clock; defensively verify a non-monotonic
    # clock never produces negative refill or a crash.
    class BuggyClock:
        def __init__(self):
            self.t = 1000.0

        def __call__(self):
            return self.t

    clk = BuggyClock()
    rl = RateLimiter(capacity=5, refill_rate=1, ttl=600, clock=clk)
    rl.try_acquire("k")
    clk.t = 500.0  # clock moved backwards
    assert rl.try_acquire("k") in (True, False)  # no crash, no negative tokens
    assert rl.available("k") >= 0


# ---------------------------------------------------------------------------
# refresh callback + the no-lock-during-user-code invariant
# ---------------------------------------------------------------------------
def test_refresh_called_once_per_key():
    clk = FakeClock()
    calls = []

    def refresh(key):
        calls.append(key)
        return 3.0  # start this key with 3 tokens

    rl = RateLimiter(capacity=10, refill_rate=0, ttl=600, clock=clk,
                     refresh=refresh, sweep_interval=1)
    assert rl.try_acquire("k") is True
    assert rl.try_acquire("k") is True
    assert rl.try_acquire("k") is True
    assert rl.try_acquire("k") is False  # only 3 tokens available
    assert len(calls) == 1  # refresh ran exactly once, not on the hot path


def test_refresh_error_fails_open():
    clk = FakeClock()

    def refresh(key):
        raise IOError("backend down")

    rl = RateLimiter(capacity=5, refill_rate=0, ttl=600, clock=clk,
                     refresh=refresh, sweep_interval=1)
    assert rl.try_acquire("k") is True  # fell back to full capacity


def test_no_lock_during_user_code():
    # refresh performs a blocking "I/O"; if the lock were held we would deadlock
    # because refresh itself calls try_acquire on the same key.
    clk = FakeClock()
    rl = RateLimiter(capacity=5, refill_rate=0, ttl=600, clock=clk,
                     sweep_interval=1)

    def refresh(key):
        # Attempt to consume while "inside" the hook. If the main path held the
        # lock, this would deadlock; it returns immediately => lock was released.
        assert rl.try_acquire(key) is True
        return 5.0

    rl._refresh = refresh
    assert rl.try_acquire("k") is True


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------
def test_concurrent_consumption_respects_capacity():
    # No refill: at most `capacity` successes across all threads.
    rl = RateLimiter(capacity=100, refill_rate=0, ttl=600, clock=FakeClock(),
                     sweep_interval=1)
    results = []
    lock = threading.Lock()

    def worker():
        local = [rl.try_acquire("shared") for _ in range(50)]
        with lock:
            results.extend(local)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(1 for r in results if r) == 100  # exactly capacity successes
    assert len(results) == 20 * 50


def test_concurrent_many_keys_no_crash_and_bounded():
    rl = RateLimiter(capacity=1, refill_rate=0, ttl=600, clock=FakeClock(),
                     sweep_interval=1)

    def worker(i):
        for _ in range(1000):
            rl.try_acquire(f"key-{i % 50}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(rl) <= 50


def test_real_clock_smoke():
    rl = RateLimiter(capacity=3, refill_rate=100)  # real time.monotonic
    assert [rl.try_acquire("k") for _ in range(3)] == [True, True, True]
    assert rl.try_acquire("k") is False
    time.sleep(0.05)  # ~5 tokens at 100/s
    assert rl.try_acquire("k") is True


if __name__ == "__main__":
    import sys

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {exc!r}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
