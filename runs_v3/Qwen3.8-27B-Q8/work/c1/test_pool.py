"""Tests for ConnectionPool.

These tests are written to *demonstrate* the two properties the task calls out,
not merely to exercise the happy path:

  1. FIFO fairness: a late arrival must never take a connection ahead of a
     thread that has been waiting longer.
  2. The lock invariant: no lock is held while the user-supplied factory/close
     callables run, and no lock is held while a thread is blocked waiting.

Run with:  python3 test_pool.py
"""

import threading
import time

from pool import ConnectionPool


def wait_until(pred, timeout=5.0):
    """Poll pred() until true or timeout. Raises AssertionError on timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.001)
    raise AssertionError("condition not met within %.1fs" % timeout)


# ---------------------------------------------------------------------------
# 1. FIFO fairness
# ---------------------------------------------------------------------------

def test_fifo_fairness():
    """Three waiters queue up behind the single held connection. They must be
    served in the exact order they started waiting (B, C, D), even though the
    connection is released only once and then ping-pongs between them."""
    pool = ConnectionPool(factory=lambda: object(), close=lambda c: None,
                          max_size=1)
    held = pool.acquire()  # main thread holds the only connection

    order = []
    order_lock = threading.Lock()

    def requester(name):
        c = pool.acquire(timeout=5, _waiter_name=name)
        with order_lock:
            order.append(name)
        pool.release(c)  # hands the connection to the next waiter in FIFO order

    # Start the waiters one at a time, and only start the next one once the
    # previous one is observably sitting in the waiter queue. This pins down
    # the queue order to B, C, D before any connection is freed.
    for name in ("B", "C", "D"):
        t = threading.Thread(target=requester, args=(name,))
        t.start()
        wait_until(lambda n=name: pool.waiter_count() >=
                   {"B": 1, "C": 2, "D": 3}[n])

    # White-box check of the queue order itself.
    with pool._lock:
        queued = [w.name for w in pool._waiters]
    assert queued == ["B", "C", "D"], f"queue order was {queued}"

    pool.release(held)  # frees the connection; should go to B, then C, then D

    wait_until(lambda: len(order) == 3)
    assert order == ["B", "C", "D"], f"served order was {order}"
    print("PASS test_fifo_fairness: served order", order)


def test_late_arrival_cannot_jump_queue():
    """A thread that arrives *after* B and C are already waiting must be served
    last, even though at the moment it arrives the pool could in principle grow
    (we keep it from growing by holding the connection)."""
    pool = ConnectionPool(factory=lambda: object(), close=lambda c: None,
                          max_size=1)
    held = pool.acquire()

    order = []
    order_lock = threading.Lock()

    def requester(name):
        c = pool.acquire(timeout=5, _waiter_name=name)
        with order_lock:
            order.append(name)
        pool.release(c)

    tb = threading.Thread(target=requester, args=("B",))
    tb.start()
    wait_until(lambda: pool.waiter_count() == 1)
    tc = threading.Thread(target=requester, args=("C",))
    tc.start()
    wait_until(lambda: pool.waiter_count() == 2)

    # Late arrival: enters while two threads are already waiting.
    td = threading.Thread(target=requester, args=("D-late",))
    td.start()
    wait_until(lambda: pool.waiter_count() == 3)

    pool.release(held)
    wait_until(lambda: len(order) == 3)
    assert order == ["B", "C", "D-late"], f"served order was {order}"
    print("PASS test_late_arrival_cannot_jump_queue: served order", order)


# ---------------------------------------------------------------------------
# 2. Lock invariant
# ---------------------------------------------------------------------------

def test_no_lock_held_during_factory_and_close():
    """The factory and close callables assert that the pool's lock is FREE at
    the moment they run. If the pool ever held the lock across a factory/close
    call, the non-blocking acquire() below would fail and the test would fail."""
    violations = []

    def make_pool():
        def factory():
            if not pool._lock.acquire(blocking=False):
                violations.append("factory ran while pool lock was held")
            else:
                pool._lock.release()
            return object()

        def close(conn):
            if not pool._lock.acquire(blocking=False):
                violations.append("close ran while pool lock was held")
            else:
                pool._lock.release()

        return ConnectionPool(factory=factory, close=close, max_size=2)

    pool = make_pool()

    # Exercise creation (factory) and idle eviction (close).
    idle_events = []
    conns = [pool.acquire() for _ in range(2)]
    for c in conns:
        pool.release(c)

    # Force the idle connections to go stale, then acquire to trigger lazy
    # close() of each of them.
    pool._idle_ttl = 0.0
    for _ in range(2):
        pool.acquire(timeout=5)

    assert not violations, f"invariant violated: {violations}"
    print("PASS test_no_lock_held_during_factory_and_close")


def test_no_lock_held_while_blocked_waiting():
    """A thread blocked in acquire() must not hold the pool lock. We prove this
    by showing the main thread can acquire the pool lock *while* the other
    thread is observably parked in the waiter queue."""
    pool = ConnectionPool(factory=lambda: object(), close=lambda c: None,
                          max_size=1)
    held = pool.acquire()

    started = threading.Event()

    def waiter():
        started.set()
        pool.acquire(timeout=5)

    t = threading.Thread(target=waiter)
    t.start()
    started.wait()
    wait_until(lambda: pool.waiter_count() == 1)

    # The waiter is blocked. If it held the lock, this acquire would deadlock.
    got = pool._lock.acquire(blocking=False)
    assert got, "blocked waiter was holding the pool lock"
    pool._lock.release()

    pool.release(held)
    t.join(timeout=5)
    assert not t.is_alive(), "waiter did not wake up"
    print("PASS test_no_lock_held_while_blocked_waiting")


# ---------------------------------------------------------------------------
# Supporting behaviour (timeout, idle eviction, reuse)
# ---------------------------------------------------------------------------

def test_acquire_timeout():
    pool = ConnectionPool(factory=lambda: object(), close=lambda c: None,
                          max_size=1)
    held = pool.acquire()
    t0 = time.monotonic()
    try:
        pool.acquire(timeout=0.2)
        raise AssertionError("expected TimeoutError")
    except TimeoutError:
        elapsed = time.monotonic() - t0
    assert 0.15 <= elapsed <= 2.0, f"unexpected elapsed {elapsed}"
    pool.release(held)
    print("PASS test_acquire_timeout")


def test_idle_eviction_lazy():
    """A connection idle longer than idle_ttl is closed and replaced on the next
    acquire; nothing happens in the background."""
    closed = []
    pool = ConnectionPool(factory=lambda: object(), close=closed.append,
                          max_size=2, idle_ttl=0.05)
    c1 = pool.acquire()
    pool.release(c1)
    time.sleep(0.1)  # let it go stale; no close() should have fired yet
    assert closed == [], f"background close observed: {closed}"
    c2 = pool.acquire()
    assert c2 is not c1, "stale connection was reused instead of replaced"
    assert closed == [c1], f"expected [c1] closed, got {closed}"
    pool.release(c2)
    print("PASS test_idle_eviction_lazy")


def test_reuse_and_bounds():
    """The pool never exceeds max_size live connections, and released
    connections are reused rather than duplicated."""
    created = []
    lock = threading.Lock()

    def factory():
        c = object()
        with lock:
            created.append(c)
        return c

    pool = ConnectionPool(factory=factory, close=lambda c: None, max_size=3)
    a = pool.acquire()
    b = pool.acquire()
    c = pool.acquire()
    assert pool.live_count() == 3, pool.live_count()
    assert len(created) == 3, f"created {len(created)} connections"

    pool.release(a)
    d = pool.acquire(timeout=5)  # must reuse the released `a`, not create
    assert d is a, "released connection was not reused"
    assert pool.live_count() == 3, pool.live_count()
    assert len(created) == 3, f"pool grew past max_size: {len(created)}"
    for x in (b, c, d):
        pool.release(x)
    print("PASS test_reuse_and_bounds")


def main():
    test_fifo_fairness()
    test_late_arrival_cannot_jump_queue()
    test_no_lock_held_during_factory_and_close()
    test_no_lock_held_while_blocked_waiting()
    test_acquire_timeout()
    test_idle_eviction_lazy()
    test_reuse_and_bounds()
    print("ALL C1 TESTS PASSED")


if __name__ == "__main__":
    main()
