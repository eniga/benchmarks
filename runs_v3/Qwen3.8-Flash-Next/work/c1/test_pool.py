"""Tests for the FIFO connection pool in pool.py (task C1).

Run:  python3 test_pool.py     (plain stdlib, no pytest needed)

The tests are deliberately built around the two properties the task asks for:

* strict FIFO fairness - including "a late arrival must not barge in";
* the invariant that no lock is held while the user's factory/close runs and
  no lock is held while a thread is blocked waiting.

Every test is deterministic: queue order is established by polling the pool's
own waiter count, so the expected service order is known before the trigger.
"""

from __future__ import annotations

import random
import threading
import time
import traceback

from pool import ConnectionPool, DEFAULT_IDLE_TIMEOUT


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
class Conn:
    def __init__(self, cid: int) -> None:
        self.cid = cid
        self.closed = False

    def __repr__(self) -> str:
        return f"Conn({self.cid})"


class Probe:
    """Counts factory/close calls and checks the pool lock at call time.

    Safe to interpret literally only when no *other* thread is exercising the
    pool: the pool lock is held for microseconds at a time during normal use,
    so a failed probe in a busy stress test would be ambiguous.  The
    lock-invariant tests below therefore run with the pool touched only by the
    thread under test (plus blocked waiters, which by design hold nothing).
    """

    def __init__(self, factory_delay: float = 0.0) -> None:
        self.pool_ref: list = []          # [pool] filled in after construction
        self.factory_calls = 0
        self.close_calls = 0
        self.lock_held_at_factory = 0
        self.lock_held_at_close = 0
        self.factory_threads = set()
        self.close_threads = set()
        self.closed_conns: list = []
        self.created: list[Conn] = []
        self.live = 0            # connections that exist right now (idle + leased)
        self.peak_live = 0
        self._probe_lock = threading.Lock()   # test bookkeeping, not the pool lock
        self._n = 0
        self._factory_delay = factory_delay
        self.fail_next = False

    def factory(self) -> Conn:
        with self._probe_lock:
            self.factory_calls += 1
        self._observe("factory")
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("factory boom")
        if self._factory_delay:
            time.sleep(self._factory_delay)
        c = Conn(self._n)
        self._n += 1
        self.created.append(c)
        with self._probe_lock:
            self.live += 1
            self.peak_live = max(self.peak_live, self.live)
        return c

    def close(self, conn: Conn) -> None:
        with self._probe_lock:
            self.close_calls += 1
        self._observe("close")
        conn.closed = True
        self.closed_conns.append(conn)
        with self._probe_lock:
            self.live -= 1

    def _observe(self, kind: str) -> None:
        pool = self.pool_ref[0]
        assert pool is not None
        free = pool._lock.acquire(blocking=False)
        with self._probe_lock:
            if not free:
                if kind == "factory":
                    self.lock_held_at_factory += 1
                else:
                    self.lock_held_at_close += 1
            tid = threading.current_thread().name
            (self.factory_threads if kind == "factory" else self.close_threads).add(tid)
        if free:
            pool._lock.release()


def make_pool(max_size: int, factory_delay: float = 0.0, idle_timeout: float = DEFAULT_IDLE_TIMEOUT,
             clock=time.monotonic):
    probe = Probe(factory_delay=factory_delay)
    pool = ConnectionPool(max_size, probe.factory, probe.close,
                          idle_timeout=idle_timeout, clock=clock)
    probe.pool_ref.append(pool)
    return pool, probe


class FakeClock:
    """Monotonic fake clock (never goes backwards)."""

    def __init__(self, t: float = 1000.0) -> None:
        self.t = t
        self._l = threading.Lock()

    def __call__(self) -> float:
        with self._l:
            return self.t

    def advance(self, dt: float) -> None:
        with self._l:
            self.t += dt


def wait_until(pred, timeout=5.0, step=0.001):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(step)
    return False


def waiters_of(pool):
    return pool.counts()["waiting"]


def lock_is_free(pool) -> bool:
    if pool._lock.acquire(blocking=False):
        pool._lock.release()
        return True
    return False


# --------------------------------------------------------------------------
# tests
# --------------------------------------------------------------------------
def test_construction_limits():
    pool, _ = make_pool(2)
    assert pool.max_size == 2
    assert DEFAULT_IDLE_TIMEOUT == 60.0
    assert pool.idle_timeout == 60.0          # default is 60 s as specified
    try:
        ConnectionPool(0, lambda: object(), lambda c: None)
    except ValueError:
        pass
    else:
        raise AssertionError("max_size=0 should be rejected")


def test_timeout_when_exhausted():
    pool, _ = make_pool(1)
    a = pool.acquire()
    t0 = time.monotonic()
    try:
        pool.acquire(timeout=0.05)
    except TimeoutError as e:
        waited = time.monotonic() - t0
        assert 0.04 <= waited < 0.5, waited
        assert a.cid == 0
        pool.release(a)
    else:
        raise AssertionError("expected TimeoutError")
    # timeout=0 must fail immediately when nothing is free
    try:
        pool.acquire()                       # refills
        try:
            pool.acquire(timeout=0)
        except TimeoutError:
            pass
        else:
            raise AssertionError("expected TimeoutError for timeout=0")
    finally:
        pool.drain()


def test_release_foreign_connection_rejected():
    pool, _ = make_pool(1)
    a = pool.acquire()
    pool.release(a)
    for bad in (a, Conn(999)):
        try:
            pool.release(bad)
        except RuntimeError:
            pass
        else:
            raise AssertionError("expected RuntimeError for foreign/double release")


def test_fifo_handoff_order():
    """5 queued waiters are served in exactly the order they queued."""
    violations = 0
    for trial in range(20):
        pool, _ = make_pool(1)
        holder = pool.acquire()
        served: list[int] = []
        started: list[int] = []

        def worker(i: int) -> None:
            conn = pool.acquire(timeout=5)
            served.append(i)
            time.sleep(0.005)               # hold briefly, then pass it on
            pool.release(conn)

        for i in range(5):
            th = threading.Thread(target=worker, args=(i,), name=f"w{i}")
            th.start()
            assert wait_until(lambda: waiters_of(pool) == i + 1), f"waiter {i} never queued"
            started.append(i)
        assert waiters_of(pool) == 5
        pool.release(holder)                # hand-off chain begins
        time.sleep(0.25)
        if served != started:
            violations += 1
            print(f"    trial {trial}: served={served} expected={started}")
        assert pool.counts()["leased"] == 0 and pool.counts()["idle"] == 1
    assert violations == 0, f"FIFO violated in {violations}/20 trials"


def test_late_arrival_cannot_barge_in():
    """A thread that shows up after the queue must be served last."""
    violations = 0
    for trial in range(20):
        pool, _ = make_pool(1)
        holder = pool.acquire()
        served: list[str] = []

        def worker(i: int) -> None:
            conn = pool.acquire(timeout=5)
            served.append(f"w{i}")
            time.sleep(0.005)
            pool.release(conn)

        for i in range(4):
            threading.Thread(target=worker, args=(i,), name=f"w{i}").start()
            assert wait_until(lambda: waiters_of(pool) == i + 1)

        def late() -> None:
            conn = pool.acquire(timeout=5)
            served.append("late")
            pool.release(conn)

        threading.Thread(target=late, name="late").start()
        assert wait_until(lambda: waiters_of(pool) == 5), "late arrival never queued"
        pool.release(holder)
        time.sleep(0.25)
        if served != ["w0", "w1", "w2", "w3", "late"]:
            violations += 1
            print(f"    trial {trial}: served={served}")
    assert violations == 0, f"late arrival barged in {violations}/20 trials"


def test_burst_release_keeps_queue_order():
    """Two slots, 6 queued waiters, 2 late arrivals: hand-off order is queue order.

    The pool is allowed to hand two connections over at nearly the same moment,
    and the two woken threads then append to a shared list in whichever order
    the scheduler runs them - so the observable "served" sequence is not a
    reliable witness for the fairness of a 2-slot burst (it is reliable when
    max_size == 1, which is what the two single-slot FIFO tests assert).
    What FCFS actually governs is the order in which the pool earmarks
    connections, recorded in pool.last_handoffs, and that is what this asserts.
    """
    pool, _ = make_pool(2)
    h = [pool.acquire(), pool.acquire()]
    served: list[str] = []
    name_by_ident: dict[int, str] = {}

    def worker(i: int) -> None:
        name_by_ident[threading.get_ident()] = f"q{i}"
        conn = pool.acquire(timeout=5)
        served.append(f"q{i}")
        time.sleep(0.004)
        pool.release(conn)

    for i in range(6):
        threading.Thread(target=worker, args=(i,), name=f"q{i}").start()
        assert wait_until(lambda: waiters_of(pool) == i + 1)

    def late(tag: str) -> None:
        name_by_ident[threading.get_ident()] = tag
        conn = pool.acquire(timeout=5)
        served.append(tag)
        time.sleep(0.004)
        pool.release(conn)

    for tag in ("lateA", "lateB"):
        threading.Thread(target=late, args=(tag,), name=tag).start()
    assert wait_until(lambda: waiters_of(pool) == 8)

    pool.release(h[0])
    pool.release(h[1])
    assert wait_until(lambda: len(pool.last_handoffs) == 8), list(pool.last_handoffs)
    time.sleep(0.05)

    order = [name_by_ident[i] for i in pool.last_handoffs]
    expected = [f"q{i}" for i in range(6)] + ["lateA", "lateB"]
    assert order == expected, order
    assert sorted(served) == sorted(expected), served
    assert pool.counts()["waiting"] == 0, pool.counts()


def test_no_lock_held_while_threads_block():
    pool, _ = make_pool(1, factory_delay=0.0)
    holder = pool.acquire()
    blocked = []
    def blocked_worker():
        try:
            conn = pool.acquire(timeout=0.5)
        except TimeoutError:
            return                      # expected: the holder never gives it back
        pool.release(conn)

    for i in range(3):
        th = threading.Thread(target=blocked_worker, name=f"blk{i}")
        th.start()
        blocked.append(th)
    assert wait_until(lambda: waiters_of(pool) == 3)
    # All three waiters are blocked: none of them may hold the pool lock.
    probes = [lock_is_free(pool) for _ in range(200)]
    assert all(probes), "pool lock held while waiters were blocked"
    # And the connection holder must not hold it either.
    assert lock_is_free(pool)
    pool.release(holder)
    for th in blocked:
        th.join(2)


def test_factory_and_close_never_under_lock():
    """Single-threaded: a held pool lock at factory/close time is unambiguous."""
    clock = FakeClock()
    pool, probe = make_pool(2, factory_delay=0.01, idle_timeout=60.0, clock=clock)
    a = pool.acquire()
    b = pool.acquire()
    pool.release(a)
    clock.advance(61)                       # a is now over-age
    c = pool.acquire()                      # closes a lazily, then creates c
    assert c is not a
    pool.release(b)
    pool.release(c)
    pool.drain()
    assert probe.lock_held_at_factory == 0, probe.lock_held_at_factory
    assert probe.lock_held_at_close == 0, probe.lock_held_at_close
    assert probe.factory_calls == 3 and probe.close_calls == 3, (probe.factory_calls, probe.close_calls)
    main = threading.current_thread().name
    assert probe.factory_threads == {main}, probe.factory_threads
    assert probe.close_threads == {main}, probe.close_threads
    assert probe.closed_conns[0] is probe.created[0]      # the over-age one


def test_factory_runs_on_requesting_thread_not_under_lock():
    pool, probe = make_pool(2, factory_delay=0.20)
    a = pool.acquire()                       # factory on the main thread; held
    errors = []

    def worker() -> None:
        try:
            conn = pool.acquire(timeout=5)
        except Exception as exc:
            errors.append(exc)
        else:
            pool.release(conn)

    th = threading.Thread(target=worker, name="slow-seeker")
    th.start()
    # The worker is now inside the user factory (it sleeps 200 ms there);
    # the main thread must be able to take the pool lock right now.
    assert wait_until(lambda: probe.factory_calls == 2, timeout=1.0)
    probes = [lock_is_free(pool) for _ in range(20)]
    th.join(5)
    pool.release(a)
    assert not errors, errors
    assert probe.factory_calls == 2, probe.factory_calls
    assert probe.factory_threads == {"MainThread", "slow-seeker"}, probe.factory_threads
    assert all(probes), "pool lock was held while the factory was running"


def test_idle_expiry_is_lazy_and_only_after_60s():
    clock = FakeClock()
    pool, probe = make_pool(1, idle_timeout=60.0, clock=clock)
    a = pool.acquire()
    assert probe.factory_calls == 1 and probe.close_calls == 0
    pool.release(a)
    clock.advance(59.9)
    b = pool.acquire()                       # still fresh: reused, no new factory call
    assert b is a and probe.factory_calls == 1 and probe.close_calls == 0
    pool.release(b)
    clock.advance(60.1)                      # idle again for more than 60 s
    assert probe.close_calls == 0            # nothing closed while nobody acquired
    c = pool.acquire()
    assert c is not a
    assert probe.close_calls == 1 and probe.factory_calls == 2
    assert probe.closed_conns == [a] and a.closed
    assert c.closed is False


def test_no_background_threads_or_timers():
    pool, _ = make_pool(3)
    before = set(t.name for t in threading.enumerate())
    conns = [pool.acquire() for _ in range(3)]
    for c in conns:
        pool.release(c)
    for _ in range(5):
        try:
            pool.acquire(timeout=0.001)
        except TimeoutError:
            pass
    pool.drain()
    after = set(t.name for t in threading.enumerate())
    assert before == after, (before, after)


def test_factory_failure_releases_reserved_slot():
    pool, probe = make_pool(2)
    a = pool.acquire()
    probe.fail_next = True
    try:
        pool.acquire()
    except RuntimeError:
        pass
    else:
        raise AssertionError("factory error should propagate")
    snapshot = pool.counts()
    assert snapshot["creating"] == 0 and snapshot["waiting"] == 0, snapshot
    b = pool.acquire()                        # slot was not leaked
    assert b.cid == 1                          # only two successful factories
    assert pool.counts()["leased"] == 2
    pool.release(a)
    pool.release(b)
    pool.drain()
    assert pool.counts()["idle"] == 0


def test_failure_wakes_queued_waiter():
    pool, probe = make_pool(2)
    a = pool.acquire()
    probe.fail_next = True

    result = []

    def worker() -> None:
        try:
            conn = pool.acquire(timeout=5)
        except Exception as exc:
            result.append(("err", type(exc).__name__))
        else:
            result.append(("ok", conn.cid))
            pool.release(conn)

    th = threading.Thread(target=worker, name="seeker")
    th.start()
    time.sleep(0.05)                          # worker reserved a slot, factory failed
    th.join(5)
    assert result and result[0][0] == "err", result
    assert pool.counts()["creating"] == 0
    c = pool.acquire(timeout=2)               # capacity really was returned
    pool.release(a)
    pool.release(c)
    pool.drain()


def test_stress_capacity_and_no_deadlock():
    pool, probe = make_pool(8)
    stop = time.monotonic() + 3.0
    errors: list[str] = []
    rnd_seed = iter(range(1000))

    def churn(seed: int) -> None:
        rng = random.Random(seed)
        while time.monotonic() < stop:
            try:
                conn = pool.acquire(timeout=2.0)
            except TimeoutError:
                errors.append("timeout")
                continue
            time.sleep(rng.random() * 0.002)
            pool.release(conn)
            if rng.random() < 0.01:
                pool.drain()                 # exercise lazy/expiry-free closes too

    threads = [threading.Thread(target=churn, args=(next(rnd_seed),), name=f"c{i}")
               for i in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
        assert not t.is_alive(), "possible deadlock"
    assert not errors, errors[:5]
    assert probe.peak_live <= 8, f"peak live connections {probe.peak_live} > max_size 8"
    snapshot = pool.counts()
    assert snapshot["leased"] == 0, snapshot
    assert snapshot["idle"] + snapshot["closed"] == snapshot["created"]
    assert probe.lock_held_at_factory == 0 and probe.lock_held_at_close == 0


# --------------------------------------------------------------------------
# runner
# --------------------------------------------------------------------------
def main() -> int:
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failures = 0
    for name, fn in tests:
        t0 = time.monotonic()
        try:
            fn()
        except Exception:
            failures += 1
            print(f"FAIL {name} ({time.monotonic() - t0:.3f}s)")
            traceback.print_exc()
        else:
            print(f"PASS {name} ({time.monotonic() - t0:.3f}s)")
    print(f"\n{len(tests) - failures}/{len(tests)} tests passed "
          f"({len(tests)} run, {failures} failed)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
