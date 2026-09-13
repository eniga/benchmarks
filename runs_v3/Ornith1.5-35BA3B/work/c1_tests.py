"""Tests demonstrating FIFO fairness and the pool invariants.

Run: python3 c1_tests.py
"""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(__file__))
from c1_pool import ConnectionPool  # noqa: E402

LOCK = threading.Lock()
ORDER = []


def make_factory_and_close():
    created = []
    closed = []
    lock = threading.Lock()
    holder = []  # filled in once the pool is constructed

    def factory():
        # Invariant: while the factory runs, the pool lock must be FREE.
        p = holder[0]
        got = p._lock.acquire(timeout=0.1)
        assert got, "INVARIANT VIOLATED: factory ran while pool lock was held"
        p._lock.release()
        with lock:
            created.append(1)
        time.sleep(0.01)  # simulate blocking I/O
        return object()

    def close(conn):
        # Invariant: while close runs, the pool lock must be FREE.
        p = holder[0]
        got = p._lock.acquire(timeout=0.1)
        assert got, "INVARIANT VIOLATED: close ran while pool lock was held"
        p._lock.release()
        with lock:
            closed.append(1)
        time.sleep(0.01)

    return factory, close, created, closed, holder


def test_basic_release_reuse():
    factory, close, created, closed, holder = make_factory_and_close()
    pool = ConnectionPool(factory, close, max_size=2)
    holder.append(pool)
    a = pool.acquire(timeout=1)
    b = pool.acquire(timeout=1)
    assert pool.size == 2 and pool.available == 0
    pool.release(a)
    pool.release(b)
    c = pool.acquire(timeout=1)  # should reuse an alive connection
    assert pool.size == 2, pool.size
    assert len(created) == 2, created  # no new connection created
    assert len(closed) == 0, closed
    pool.release(c)
    print("test_basic_release_reuse: PASS")


def test_fifo_ordering():
    """Waiters are served strictly in the order they queued."""
    global ORDER
    ORDER = []
    factory, close, created, closed, holder = make_factory_and_close()
    pool = ConnectionPool(factory, close, max_size=1)
    holder.append(pool)

    reached = [threading.Event() for _ in range(4)]

    def worker(idx):
        reached[idx].set()
        conn = pool.acquire(timeout=5)
        with LOCK:
            ORDER.append(idx)
        time.sleep(0.01)
        pool.release(conn)

    holder_conn = pool.acquire(timeout=1)  # main holds the single connection
    threads = []
    for idx in range(4):
        t = threading.Thread(target=worker, args=(idx,))
        t.start()
        threads.append(t)
        # Confirm this worker reached and enqueued before starting the next.
        assert reached[idx].wait(timeout=2)
        for _ in range(2000):
            with pool._lock:
                if len(pool._waiters) == idx + 1:
                    break
            time.sleep(0.002)
        assert len(pool._waiters) == idx + 1, len(pool._waiters)

    assert pool.active == 1
    pool.release(holder_conn)  # start the FIFO chain
    for t in threads:
        t.join(timeout=5)

    assert ORDER == [0, 1, 2, 3], ORDER
    print("test_fifo_ordering: PASS (order=%s)" % ORDER)


def test_late_arrival_never_jumps_ahead():
    """A thread that arrives after others are queued is served last."""
    global ORDER
    ORDER = []
    factory, close, created, closed, holder = make_factory_and_close()
    pool = ConnectionPool(factory, close, max_size=1)
    holder.append(pool)

    reached = [threading.Event() for _ in range(4)]

    def worker(idx):
        reached[idx].set()
        conn = pool.acquire(timeout=5)
        with LOCK:
            ORDER.append(idx)
        time.sleep(0.01)
        pool.release(conn)

    holder_conn = pool.acquire(timeout=1)
    threads = []
    # Enqueue 0,1,2 first (each confirmed enqueued before the next starts).
    for idx in (0, 1, 2):
        t = threading.Thread(target=worker, args=(idx,))
        t.start()
        threads.append(t)
        assert reached[idx].wait(timeout=2)
        for _ in range(2000):
            with pool._lock:
                if len(pool._waiters) == idx + 1:
                    break
            time.sleep(0.002)

    # A late arrival (3) starts only after 0,1,2 are already queued.
    time.sleep(0.05)
    tl = threading.Thread(target=worker, args=(3,))
    tl.start()
    threads.append(tl)
    assert reached[3].wait(timeout=2)
    for _ in range(2000):
        with pool._lock:
            if len(pool._waiters) == 4:
                break
        time.sleep(0.002)

    pool.release(holder_conn)  # start the chain
    for t in threads:
        t.join(timeout=5)

    # The late arrival (3) must be served last, after the earlier waiters.
    assert ORDER == [0, 1, 2, 3], ORDER
    print("test_late_arrival_never_jumps_ahead: PASS (order=%s)" % ORDER)


def test_no_lock_while_waiting():
    """While a thread is blocked on acquire, the pool lock must be free."""
    factory, close, created, closed, holder = make_factory_and_close()
    pool = ConnectionPool(factory, close, max_size=1)
    holder.append(pool)
    pool.acquire(timeout=1)  # hold the only connection

    result = {}

    def prober():
        got = pool._lock.acquire(timeout=0.3)
        result["lock_free"] = got
        if got:
            pool._lock.release()

    def waiter():
        p = threading.Thread(target=prober)
        p.start()
        p.join()
        try:
            pool.acquire(timeout=0.2)
            result["got"] = True
        except TimeoutError:
            result["timed_out"] = True

    w = threading.Thread(target=waiter)
    w.start()
    w.join(timeout=5)
    assert result.get("lock_free") is True, result
    assert result.get("timed_out") is True, result
    print("test_no_lock_while_waiting: PASS")


def test_idle_replacement():
    """Idle connections older than the TTL are closed and lazily replaced."""
    factory, close, created, closed, holder = make_factory_and_close()
    pool = ConnectionPool(factory, close, max_size=1, idle_ttl=0.05)
    holder.append(pool)
    c = pool.acquire(timeout=1)
    pool.release(c)  # now idle
    time.sleep(0.15)  # let it exceed the TTL
    c2 = pool.acquire(timeout=1)  # should purge the stale one and create new
    assert c2 is not c, "expected a freshly created connection"
    assert pool.size == 1, pool.size
    pool.release(c2)
    assert len(closed) >= 1, closed  # the stale connection was closed
    print("test_idle_replacement: PASS (closed=%d)" % len(closed))


def test_timeout():
    factory, close, created, closed, holder = make_factory_and_close()
    pool = ConnectionPool(factory, close, max_size=1)
    holder.append(pool)
    pool.acquire(timeout=1)
    t0 = time.monotonic()
    try:
        pool.acquire(timeout=0.2)
        assert False, "expected TimeoutError"
    except TimeoutError:
        assert 0.2 <= time.monotonic() - t0 < 2
    print("test_timeout: PASS")


if __name__ == "__main__":
    test_basic_release_reuse()
    test_fifo_ordering()
    test_late_arrival_never_jumps_ahead()
    test_no_lock_while_waiting()
    test_idle_replacement()
    test_timeout()
    print("ALL C1 TESTS PASSED")
