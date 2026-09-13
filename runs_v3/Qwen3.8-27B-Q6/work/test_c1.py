"""Tests for the C1 connection pool: FIFO fairness, invariants, idle timeout."""

import sys
import threading
import time

sys.path.insert(0, ".")
from c1_pool import ConnectionPool, _lock_held


def make_pool(max_size, idle_timeout=60.0, record=None):
    """Return (pool, factory, close) where factory/close record calls and
    assert the pool lock is free while they run (the C1 invariant)."""
    created = []
    closed = []

    def factory():
        assert not _lock_held(pool), "pool held its lock while calling factory"
        c = object()
        created.append(c)
        return c

    def close(conn):
        assert not _lock_held(pool), "pool held its lock while calling close"
        closed.append(conn)

    pool = ConnectionPool(factory, close, max_size, idle_timeout=idle_timeout)
    return pool, created, closed


def test_happy_path():
    pool, created, closed = make_pool(2)
    a = pool.acquire()
    b = pool.acquire()
    assert a is not b
    pool.release(a)
    pool.release(b)
    c = pool.acquire()  # reuses an idle connection
    assert c in (a, b)
    pool.release(c)
    assert len(created) == 2, created
    assert closed == []
    print("test_happy_path OK")


def test_timeout():
    pool, created, closed = make_pool(1)
    a = pool.acquire()
    t0 = time.monotonic()
    try:
        pool.acquire(timeout=0.2)
        raise AssertionError("expected TimeoutError")
    except TimeoutError:
        dt = time.monotonic() - t0
        assert 0.15 <= dt <= 1.0, dt
    pool.release(a)
    print(f"test_timeout OK (waited {dt:.3f}s)")


def test_fifo_fairness():
    """One connection; N waiters must be served in the order they arrived."""
    pool, created, closed = make_pool(1)
    holder = pool.acquire()

    n = 6
    order = []
    order_lock = threading.Lock()
    go = [threading.Event() for _ in range(n)]
    errors = []

    def worker(i):
        try:
            go[i].wait()
            conn = pool.acquire(timeout=5)
            with order_lock:
                order.append(i)
            pool.release(conn)  # hand to the next waiter
        except Exception as e:  # noqa: BLE001
            errors.append(repr(e))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    # Release the waiters strictly in order so registration order is i.
    for i in range(n):
        go[i].set()
        time.sleep(0.05)
    time.sleep(0.1)  # let the last waiter register
    pool.release(holder)
    for t in threads:
        t.join()
    assert not errors, errors
    assert order == list(range(n)), f"FIFO violated: {order}"
    print(f"test_fifo_fairness OK (served order {order})")


def test_late_arrival_cannot_jump():
    """A thread arriving after waiters exist must not get a connection first."""
    pool, created, closed = make_pool(1)
    holder = pool.acquire()
    first = {}
    go_first = threading.Event()

    def early():
        go_first.wait()
        first["early"] = pool.acquire(timeout=5)
        pool.release(first["early"])

    t = threading.Thread(target=early)
    t.start()
    go_first.set()
    time.sleep(0.1)  # early is now waiting
    # Late arrival: pool is full, so it must queue behind `early`.
    late = {}
    def late_arrival():
        late["conn"] = pool.acquire(timeout=5)
    t2 = threading.Thread(target=late_arrival)
    t2.start()
    time.sleep(0.1)  # late is now waiting behind early
    pool.release(holder)
    t.join(); t2.join()
    # The early waiter must have been served first.
    assert first["early"] is holder, "late arrival jumped the queue"
    print("test_late_arrival_cannot_jump OK")


def test_idle_timeout_replaces():
    pool, created, closed = make_pool(1, idle_timeout=0.2)
    a = pool.acquire()
    pool.release(a)
    time.sleep(0.3)  # let it go stale
    b = pool.acquire()
    assert b is not a, "stale connection was reused"
    assert closed == [a], closed
    pool.release(b)
    print("test_idle_timeout_replaces OK")


def test_no_background_threads():
    before = threading.active_count()
    pool, created, closed = make_pool(2, idle_timeout=0.05)
    a = pool.acquire()
    pool.release(a)
    time.sleep(0.1)  # idle connection goes stale; nothing should close it yet
    assert closed == [], "a background closer fired"
    after = threading.active_count()
    assert after == before, (before, after)
    b = pool.acquire()  # lazy replacement happens here
    assert b is not a
    pool.release(b)
    print("test_no_background_threads OK")


def test_no_lock_while_waiting():
    """While a thread is blocked in acquire, the pool lock must be free."""
    pool, created, closed = make_pool(1)
    holder = pool.acquire()
    def waiter():
        pool.acquire(timeout=5)
    t = threading.Thread(target=waiter)
    t.start()
    time.sleep(0.1)  # waiter is now blocked in event.wait()
    # From this thread, the pool lock must be acquirable (i.e., not held by
    # the blocked waiter).
    assert not _lock_held(pool), "pool lock held while a thread waits"
    pool.release(holder)
    t.join()
    print("test_no_lock_while_waiting OK")


def test_factory_blocking_does_not_deadlock():
    """A factory that blocks on I/O must not deadlock the pool."""
    released = threading.Event()
    def factory():
        time.sleep(0.2)  # simulate slow I/O
        return object()
    def close(conn):
        pass
    pool = ConnectionPool(factory, close, 2)
    results = []
    def w():
        c = pool.acquire(timeout=5)
        results.append(c)
        pool.release(c)
    ts = [threading.Thread(target=w) for _ in range(4)]
    for t in ts: t.start()
    for t in ts: t.join()
    assert len(results) == 4
    print("test_factory_blocking_does_not_deadlock OK")


if __name__ == "__main__":
    test_happy_path()
    test_timeout()
    test_fifo_fairness()
    test_late_arrival_cannot_jump()
    test_idle_timeout_replaces()
    test_no_background_threads()
    test_no_lock_while_waiting()
    test_factory_blocking_does_not_deadlock()
    print("ALL C1 TESTS PASSED")
