"""Tests for pool.ConnectionPool: FIFO fairness, timeout, idle expiry, invariants."""

import sys
import threading
import time

sys.path.insert(0, "/Users/enigaahiante/Projects/benchmarks/testsuites/work/c1")
from pool import ConnectionPool  # noqa: E402

PASS = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    PASS.append(cond)
    return cond


class FakeConn:
    _n = 0

    def __init__(self):
        FakeConn._n += 1
        self.id = FakeConn._n


def make_pool(max_size, idle_ttl=60.0, factory_delay=0.0, close_delay=0.0):
    created, closed = [], []
    created_ev, closed_ev = threading.Event(), threading.Event()

    def factory():
        if factory_delay:
            time.sleep(factory_delay)
        c = FakeConn()
        with threading.Lock():
            created.append(c.id)
        created_ev.set()
        return c

    def close(c):
        if close_delay:
            time.sleep(close_delay)
        closed.append(c.id)
        closed_ev.set()

    p = ConnectionPool(factory, close, max_size, idle_ttl=idle_ttl)
    return p, created, closed, created_ev, closed_ev


def test_fifo_strict():
    """3 waiters queue in known order; each release hands the conn to the oldest."""
    p, created, closed, _, _ = make_pool(1)
    holder = p.acquire()
    order = []
    order_lock = threading.Lock()
    waiting = threading.Event()

    def waiter(tag):
        c = p.acquire(timeout=10)
        with order_lock:
            order.append((tag, c.id))
        p.release(c)

    ts = [threading.Thread(target=waiter, args=(t,)) for t in ("B", "C", "D")]
    for i, t in enumerate(ts):
        t.start()
        time.sleep(0.05)  # stagger so B < C < D strictly
    # ensure all are actually queued before releasing
    deadline = time.time() + 5
    while time.time() < deadline:
        with p._lock:
            if len(p._waiters) == 3:
                break
        time.sleep(0.005)
    queued = len(p._waiters)
    for _ in ts:
        p.release(holder)
        time.sleep(0.05)
    [t.join() for t in ts]
    check("FIFO: B, C, D served in arrival order",
          queued == 3 and [o[0] for o in order] == ["B", "C", "D"], str(order))


def test_late_arrival_no_jump():
    """With the pool exhausted, a late arrival must queue, not create."""
    p, created, closed, _, _ = make_pool(1)
    a = p.acquire()
    got = {}

    def b():
        got["b"] = p.acquire(timeout=10)
        p.release(got["b"])

    def c_arrives_later():
        time.sleep(0.2)  # B has been waiting 0.2s already
        got["c"] = p.acquire(timeout=10)
        p.release(got["c"])

    tb = threading.Thread(target=b)
    tc = threading.Thread(target=c_arrives_later)
    tb.start()
    time.sleep(0.1)  # B is now waiting
    tc.start()  # C arrives late
    time.sleep(0.5)  # C has had ample time to (wrongly) grab a connection
    check("late arrival C still blocked while B waited", "c" not in got, str(got))
    p.release(a)  # single release: must go to B
    tb.join()
    time.sleep(0.1)
    check("release went to B (oldest), not C", got.get("b") is a, f"got={getattr(got.get('b'),'id',None)}")
    tc.join()
    check("C then received the connection", got.get("c") is a, f"c={getattr(got.get('c'),'id',None)}")
    check("pool never grew beyond max_size", len(created) == 1, str(created))


def test_timeout():
    p, created, closed, _, _ = make_pool(1)
    a = p.acquire()
    t0 = time.monotonic()
    try:
        p.acquire(timeout=0.3)
        check("TimeoutError raised", False)
    except TimeoutError:
        check("TimeoutError raised after ~0.3s", 0.25 <= time.monotonic() - t0 <= 1.0)
    # timed-out thread must not have consumed the slot
    got = {}

    def b():
        got["b"] = p.acquire(timeout=5)

    tb = threading.Thread(target=b)
    tb.start()
    time.sleep(0.05)
    p.release(a)
    tb.join()
    check("slot after timeout went to B", got.get("b") is a)
    p.release(got["b"])


def test_idle_expiry_lazy():
    p, created, closed, _, closed_ev = make_pool(1, idle_ttl=0.2)
    a = p.acquire()
    p.release(a)
    time.sleep(0.35)
    b = p.acquire(timeout=5)
    check("expired idle conn closed and replaced lazily",
          b is not a and closed == [a.id] and created == [a.id, b.id],
          f"closed={closed} created={created}")
    p.release(b)


def test_no_lock_during_factory_and_close():
    """factory/close must run with the pool lock free; waiters must not hold it."""
    violations = []

    def factory():
        if p._lock.locked():
            violations.append("factory")
        time.sleep(0.05)  # widen the window
        return FakeConn()

    def close(c):
        if p._lock.locked():
            violations.append("close")

    p = ConnectionPool(factory, close, 2, idle_ttl=0.05)
    a = p.acquire()
    b = p.acquire()
    p.release(a)
    time.sleep(0.1)  # let a expire
    c = p.acquire(timeout=5)  # triggers close of expired 'a'
    check("no lock held during factory/close", not violations, str(violations))
    p.release(b)
    p.release(c)


def test_no_lock_while_waiting():
    p, created, closed, _, _ = make_pool(1, factory_delay=0.2)
    a = p.acquire()
    ev = threading.Event()
    observed = {}

    def waiter():
        ev.set()  # we are about to block
        time.sleep(0.05)
        observed["locked"] = p._lock.locked()  # while blocked in acquire
        c = p.acquire(timeout=5)
        p.release(c)

    t = threading.Thread(target=waiter)
    t.start()
    ev.wait()
    time.sleep(0.1)  # waiter is now blocked inside acquire
    p.release(a)
    t.join()
    check("pool lock free while thread blocked in acquire", observed.get("locked") is False)


def test_max_size_respected():
    p, created, closed, _, _ = make_pool(3)
    conns = [p.acquire(timeout=5) for _ in range(3)]
    check("factory called exactly max_size times", len(created) == 3, str(created))
    for c in conns:
        p.release(c)


if __name__ == "__main__":
    test_fifo_strict()
    test_late_arrival_no_jump()
    test_timeout()
    test_idle_expiry_lazy()
    test_no_lock_during_factory_and_close()
    test_no_lock_while_waiting()
    test_max_size_respected()
    print(f"\n{sum(PASS)}/{len(PASS)} checks passed")
    sys.exit(0 if all(PASS) else 1)
