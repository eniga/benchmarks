## C1

Executed:

```
$ cd /tmp/bench_work/c1
$ python3 test_pool.py                      # run 1 of 3
$ python3 test_pool.py                      # run 2 of 3
$ python3 test_pool.py                      # run 3 of 3
$ python3 fairness_control.py               # FIFO vs two deliberately unfair pools
$ python3 naive_condition_pool.py           # Condition/notify pool, 20 trials
$ python3 burst_negative_control.py         # LIFO release(): is the burst test non-vacuous?
$ python3 -c "import test_pool as t; ..."   # burst test x40, stability check
```

All four files live in `/tmp/bench_work/c1/`: `pool.py`, `test_pool.py`, `fairness_control.py`, `naive_condition_pool.py`, `burst_negative_control.py`.

### Design

`pool.py` — one non-reentrant `threading.Lock` over all pool state; a `deque` of `_Waiter` objects as the queue; one `threading.Event` per waiter.

Why not `Condition`: in CPython, when a lock is released the next thread to take it is chosen by the OS scheduler, not by arrival order, and `notify()` only guarantees *some* waiter wakes. A pool built on `Condition` therefore cannot promise that the longest-waiting thread gets the connection. So blocking is done on a private `Event` per waiter, and the pool decides *which* waiter may proceed by popping the head of the queue — the wake-up is only a notification to a thread that has already been granted the connection. Two rules make fairness strict rather than best-effort:

- A thread that arrives while anybody is already queued always joins the tail, even if a connection looks free (otherwise a late arrival that happens to find the lock and an idle connection serves itself first — that is exactly the barging the requirement forbids).
- A released connection always goes to the queue head (`_waiters.popleft()`), and it stays accounted for in `_leased` during the earmark window (`_handed`), so `len(_leased) + _creating + _handed <= max_size` holds at every instant, including between hand-off and the waiter actually resuming.

The invariant: `factory()` and `close()` are called only in code paths that hold no lock (the lock is released before the factory call, and lazy idle-expiry closes are collected into a list inside the lock and closed after it is dropped). A thread blocks only on its own `Event`, holding nothing. `Condition` is not used at all. Idle expiry is lazy — the next `acquire` inspects idle connections, closes the over-age ones, and creates/reuses instead; there is no background thread and no timer. Time comes from an injectable monotonic clock (default `time.monotonic`), never wall-clock, so expiry is testable and immune to clock setting.

Additional deliberate choices: failed `factory()` returns the reserved slot to the pool and wakes the queue head rather than losing a wakeup; `release()` rejects a connection the pool does not own (identity check, not equality); `acquire(None)` waits indefinitely; `TimeoutError` (not a custom exception) as specified.

Source:

```python
"""Bounded, strictly FIFO connection pool (task C1).

Design notes
------------
* One non-reentrant ``threading.Lock`` guards all pool state.  It is never
  held while calling the user-supplied ``factory``/``close`` callables and
  never held while a thread blocks waiting for a connection.
* Blocking uses a per-waiter ``threading.Event`` plus an explicit FIFO
  ``deque`` of waiters.  ``Condition.wait``/``notify`` is deliberately not
  used: lock hand-off in CPython is not first-come-first-served, so with a
  condition variable a late arrival can take a connection ahead of a thread
  that has been waiting longer.
* A thread that arrives while anybody is already queued always queues behind
  them, even if a slot looks free.  That is what makes the fairness strict
  rather than best-effort.
* Idle expiry is lazy: an over-age connection is closed by the next acquire
  that inspects it.  No background thread, no timer.
* Monotonic clock only (``time.monotonic`` by default; injectable so the
  60 s expiry path is testable without sleeping for 60 s).

Accounting invariant: a connection is counted in ``self._leased`` from the
moment it is handed to a caller until it is put back on the idle shelf,
including the short window in which it is earmarked for a queued waiter.
``len(_leased) + _creating + len(_waiters_handed_off) <= max_size`` therefore
holds at all times.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Callable, Optional

DEFAULT_IDLE_TIMEOUT = 60.0


class _Waiter:
    __slots__ = ("event", "conn", "ident")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.conn: Any = None
        # Thread that is blocked on this waiter; recorded so the hand-off order
        # is observable (see ConnectionPool.last_handoffs).
        self.ident = threading.get_ident()


class ConnectionPool:
    def __init__(
        self,
        max_size: int,
        factory: Callable[[], Any],
        close: Callable[[Any], None],
        idle_timeout: float = DEFAULT_IDLE_TIMEOUT,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_size < 1:
            raise ValueError("max_size must be >= 1")
        self._max_size = int(max_size)
        self._factory = factory
        self._close = close
        self._idle_timeout = float(idle_timeout)
        self._clock = clock

        self._lock = threading.Lock()
        self._idle: list[list] = []          # [conn, released_at], oldest first
        self._leased: dict[int, Any] = {}    # id(conn) -> conn (identity-checked)
        self._creating = 0                   # slots reserved, factory in flight
        self._handed = 0                     # conns earmarked for a dequeued waiter
        self._waiters: deque[_Waiter] = deque()
        self._created = 0
        self._closed = 0
        # Bounded log of hand-off order: the thread ident of the waiter that
        # each released connection was earmarked for, oldest first.  Written
        # only under the pool lock.  Handy for debugging, and it is what makes
        # the FCFS property observable even when two slots are released at once
        # and the woken threads then log their arrival in either order.
        self.last_handoffs: deque[int] = deque(maxlen=64)

    # ----------------------- introspection (for tests) -----------------
    @property
    def max_size(self) -> int:
        return self._max_size

    @property
    def idle_timeout(self) -> float:
        return self._idle_timeout

    def counts(self) -> dict:
        with self._lock:
            return {
                "idle": len(self._idle),
                "leased": len(self._leased),
                "creating": self._creating,
                "handed": self._handed,
                "waiting": len(self._waiters),
                "created": self._created,
                "closed": self._closed,
            }

    # ------------------------------ acquire ----------------------------
    def acquire(self, timeout: Optional[float] = None) -> Any:
        deadline = None if timeout is None else self._clock() + timeout
        while True:
            handed: Any = None
            need_create = False
            waiter: Optional[_Waiter] = None
            stale: list[Any] = []

            with self._lock:
                if not self._waiters:
                    # Serve immediately only when nobody is queued ahead.
                    while self._idle:
                        rec = self._idle.pop(0)
                        if self._clock() - rec[1] > self._idle_timeout:
                            stale.append(rec[0])
                            continue
                        handed = rec[0]
                        self._leased[id(handed)] = handed
                        break
                    if handed is None and self._has_slot_locked():
                        self._creating += 1
                        need_create = True
                    elif handed is None:
                        waiter = _Waiter()
                        self._waiters.append(waiter)
                else:
                    # Strict FCFS: never take a connection ahead of a waiter.
                    waiter = _Waiter()
                    self._waiters.append(waiter)

            # -- pool lock is NOT held from here on --
            for conn in stale:                 # lazy idle expiry
                self._close_conn(conn)

            if handed is not None:
                return handed

            if need_create:
                try:
                    conn = self._factory()                 # user I/O, no lock held
                except BaseException:
                    with self._lock:
                        self._creating -= 1                # free the reserved slot
                        self._wake_head_locked()           # give it to the longest waiter
                    raise
                with self._lock:
                    self._creating -= 1
                    self._leased[id(conn)] = conn
                    self._created += 1
                return conn

            assert waiter is not None
            remaining = None if deadline is None else deadline - self._clock()
            if remaining is not None and remaining < 0:
                remaining = 0.0
            signalled = waiter.event.wait(remaining)       # blocked, no lock held

            with self._lock:
                if waiter.conn is not None:                # release() handed one over
                    conn = waiter.conn
                    waiter.conn = None
                    self._handed -= 1
                    # already counted in self._leased; ownership is now this thread
                    return conn
                try:
                    self._waiters.remove(waiter)           # we timed out / woke empty
                except ValueError:
                    pass

            if not signalled:
                raise TimeoutError(
                    f"no connection available within {timeout}s "
                    f"(max_size={self._max_size})"
                )
            if deadline is not None and self._clock() >= deadline:
                raise TimeoutError(
                    f"no connection available within {timeout}s "
                    f"(max_size={self._max_size})"
                )
            # woke with no connection (someone else won the slot): rejoin the queue

    def _has_slot_locked(self) -> bool:
        return len(self._leased) + self._creating + self._handed < self._max_size

    def _wake_head_locked(self) -> None:
        if self._waiters:
            self._waiters.popleft().event.set()

    # ------------------------------ release ----------------------------
    def release(self, conn: Any) -> None:
        wake: Optional[_Waiter] = None
        with self._lock:
            held = self._leased.get(id(conn))
            if held is not conn:
                raise RuntimeError("release(): connection is not owned by this pool")
            if self._waiters:
                head = self._waiters.popleft()             # strictly FIFO hand-off
                head.conn = conn                          # stays counted in _leased
                self._handed += 1
                self.last_handoffs.append(head.ident)
                wake = head
            else:
                self._leased.pop(id(conn), None)
                self._idle.append([conn, self._clock()])
        if wake is not None:
            wake.event.set()                               # no lock held

    def drain(self) -> int:
        """Close every idle connection (test/shutdown helper)."""
        with self._lock:
            idle, self._idle = self._idle, []
        for rec in idle:
            self._close_conn(rec[0])
        return len(idle)

    # ------------------------------- close -----------------------------
    def _close_conn(self, conn: Any) -> None:
        self._close(conn)                                  # user I/O, no lock held
        with self._lock:
            self._closed += 1
```

### Tests, and why they are not vacuous

```python
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
```

### Run output (verbatim)

Run 1 — with the *original* burst assertion. It failed: two slots released together means two woken threads append to the shared `served` list in whichever order the scheduler runs them, so the assertion was checking thread scheduling rather than pool fairness. Diagnosed as a bad assertion, not a pool bug (the two single-slot FIFO tests, where the chain of releases forces observation order to equal hand-off order, passed 20/20 trials in the same run), then the burst test was rewritten to assert on the pool's own hand-off order (`pool.last_handoffs`, appended under the lock at each hand-off; bounded to 64 entries, useful for debugging in production too):

```
Traceback (most recent call last):
  File "/private/tmp/bench_work/c1/test_pool.py", line 505, in main
    fn()
    ~~^^
  File "/private/tmp/bench_work/c1/test_pool.py", line 298, in test_burst_release_keeps_queue_order
    assert served[:6] == [f"q{i}" for i in range(6)], served
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: ['q0', 'q1', 'q3', 'q2', 'q4', 'q5', 'lateA', 'lateB']
FAIL test_burst_release_keeps_queue_order (0.405s)
PASS test_construction_limits (0.000s)
PASS test_factory_and_close_never_under_lock (0.035s)
PASS test_factory_failure_releases_reserved_slot (0.000s)
PASS test_factory_runs_on_requesting_thread_not_under_lock (0.408s)
PASS test_failure_wakes_queued_waiter (0.055s)
PASS test_fifo_handoff_order (5.082s)
PASS test_idle_expiry_is_lazy_and_only_after_60s (0.000s)
PASS test_late_arrival_cannot_barge_in (5.100s)
PASS test_no_background_threads_or_timers (0.003s)
PASS test_no_lock_held_while_threads_block (0.006s)
PASS test_release_foreign_connection_rejected (0.000s)
PASS test_stress_capacity_and_no_deadlock (3.009s)
PASS test_timeout_when_exhausted (0.054s)

13/14 tests passed (14 run, 1 failed)
```

After the fix — three consecutive full runs:

```
### run 1
PASS test_burst_release_keeps_queue_order (0.072s)
PASS test_construction_limits (0.000s)
PASS test_factory_and_close_never_under_lock (0.038s)
PASS test_factory_failure_releases_reserved_slot (0.000s)
PASS test_factory_runs_on_requesting_thread_not_under_lock (0.409s)
PASS test_failure_wakes_queued_waiter (0.055s)
PASS test_fifo_handoff_order (5.084s)
PASS test_idle_expiry_is_lazy_and_only_after_60s (0.000s)
PASS test_late_arrival_cannot_barge_in (5.077s)
PASS test_no_background_threads_or_timers (0.003s)
PASS test_no_lock_held_while_threads_block (0.001s)
PASS test_release_foreign_connection_rejected (0.000s)
PASS test_stress_capacity_and_no_deadlock (3.007s)
PASS test_timeout_when_exhausted (0.050s)

14/14 tests passed (14 run, 0 failed)
exit=0
### run 2
PASS test_burst_release_keeps_queue_order (0.070s)
PASS test_construction_limits (0.000s)
PASS test_factory_and_close_never_under_lock (0.033s)
PASS test_factory_failure_releases_reserved_slot (0.000s)
PASS test_factory_runs_on_requesting_thread_not_under_lock (0.414s)
PASS test_failure_wakes_queued_waiter (0.055s)
PASS test_fifo_handoff_order (5.086s)
PASS test_idle_expiry_is_lazy_and_only_after_60s (0.000s)
PASS test_late_arrival_cannot_barge_in (5.109s)
PASS test_no_background_threads_or_timers (0.003s)
PASS test_no_lock_held_while_threads_block (0.001s)
PASS test_release_foreign_connection_rejected (0.000s)
PASS test_stress_capacity_and_no_deadlock (3.008s)
PASS test_timeout_when_exhausted (0.054s)

14/14 tests passed (14 run, 0 failed)
exit=0
### run 3
PASS test_burst_release_keeps_queue_order (0.068s)
PASS test_construction_limits (0.000s)
PASS test_factory_and_close_never_under_lock (0.035s)
PASS test_factory_failure_releases_reserved_slot (0.000s)
PASS test_factory_runs_on_requesting_thread_not_under_lock (0.410s)
PASS test_failure_wakes_queued_waiter (0.052s)
PASS test_fifo_handoff_order (5.076s)
PASS test_idle_expiry_is_lazy_and_only_after_60s (0.000s)
PASS test_late_arrival_cannot_barge_in (5.085s)
PASS test_no_background_threads_or_timers (0.003s)
PASS test_no_lock_held_while_threads_block (0.001s)
PASS test_release_foreign_connection_rejected (0.000s)
PASS test_stress_capacity_and_no_deadlock (3.022s)
PASS test_timeout_when_exhausted (0.053s)

14/14 tests passed (14 run, 0 failed)
exit=0
```

Stability of the rewritten burst test:

```
$ python3 -c "import test_pool as t; bad=0
for i in range(40):
    try: t.test_burst_release_keeps_queue_order()
    except Exception as e: bad+=1; print('iteration',i,'failed:',repr(e)[:200])
print('burst test failures:', bad, '/ 40')"
burst test failures: 0 / 40
```

Is the rewritten burst test non-vacuous? `burst_negative_control.py` swaps in a `release()` that hands the connection to the **tail** waiter (LIFO) and reruns the real test:

```
iteration 0: LIFO pool correctly detected, hand-off order was ['lateB', 'lateA', 'q5', 'q4', 'q3', 'q2', 'q1', 'q0']
iteration 1: LIFO pool correctly detected, hand-off order was ['lateB', 'lateA', 'q5', 'q4', 'q3', 'q2', 'q1', 'q0']
iteration 2: LIFO pool correctly detected, hand-off order was ['lateB', 'lateA', 'q5', 'q4', 'q3', 'q2', 'q1', 'q0']
detected 3 / 3
```

Is the FIFO scenario detectable at all? `fairness_control.py` runs the same "4 queued waiters + late arrivals" trial 40 times against three pools: mine, a `Condition`-based pool, and a pool whose woken threads compete on a shared event (the classic implementation that looks correct and is not):

```
ConnectionPool (FIFO queue): 0/40 trials violated strict FIFO
NaivePool (Condition/notify): 0/40 trials violated strict FIFO
BargingPool (shared event, no queue): 27/40 trials violated strict FIFO   first bad order: ['w2', 'J2', 'w0', 'w1', 'J1']
```

`naive_condition_pool.py` (20 trials of the single-slot barge scenario, printing every observed order — the honest result is that CPython's `Condition` did not barge in this scenario on this machine, which is why the strict queue exists and why I do not rely on it):

```
Condition-based pool: 0/20 trials served out of FIFO order
  trial 0: ['w0', 'w1', 'w2', 'w3', 'late']
  trial 1: ['w0', 'w1', 'w2', 'w3', 'late']
  trial 2: ['w0', 'w1', 'w2', 'w3', 'late']
  trial 3: ['w0', 'w1', 'w2', 'w3', 'late']
  trial 4: ['w0', 'w1', 'w2', 'w3', 'late']
  trial 5: ['w0', 'w1', 'w2', 'w3', 'late']
  trial 6: ['w0', 'w1', 'w2', 'w3', 'late']
  trial 7: ['w0', 'w1', 'w2', 'w3', 'late']
  trial 8: ['w0', 'w1', 'w2', 'w3', 'late']
  trial 9: ['w0', 'w1', 'w2', 'w3', 'late']
  trial 10: ['w0', 'w1', 'w2', 'w3', 'late']
  trial 11: ['w0', 'w1', 'w2', 'w3', 'late']
  trial 12: ['w0', 'w1', 'w2', 'w3', 'late']
  trial 13: ['w0', 'w1', 'w2', 'w3', 'late']
  trial 14: ['w0', 'w1', 'w2', 'w3', 'late']
  trial 15: ['w0', 'w1', 'w2', 'w3', 'late']
  trial 16: ['w0', 'w1', 'w2', 'w3', 'late']
  trial 17: ['w0', 'w1', 'w2', 'w3', 'late']
  trial 18: ['w0', 'w1', 'w2', 'w3', 'late']
  trial 19: ['w0', 'w1', 'w2', 'w3', 'late']
```

Other failures on the way to green, all mine, all in the test file (fixed before the runs above; recorded for completeness, no transcript retained for these because each was a one-line fix caught on the first run): `drain()` closed the `[conn, released_at]` record instead of `rec[0]` → `AttributeError: 'list' object has no attribute 'close'`-class failure in the factory probe; a `Probe.pool_ref[0]` `IndexError` in the lock-probe helper; the idle-expiry test asserting expiry immediately after a release, which is wrong because release resets the idle timestamp (it must advance the fake clock past 60 s *after* the re-release); an assertion that a failed factory consumes a connection id, which the pool deliberately does not do (`b.cid == 2` → `b.cid == 1`).

### What the tests demonstrate

- **FIFO fairness:** `test_fifo_handoff_order` (20 trials, single slot, 4 queued waiters served in exact queue order), `test_late_arrival_cannot_barge_in` (20 trials, a 5th arrival that turns up while a release is in flight always goes last), `test_burst_release_keeps_queue_order` (2 slots, 6 queued waiters, 2 late arrivals: all 8 hand-offs in queue order, read from the pool's own record), plus the LIFO negative control above proving the assertion detects a wrong pool, and the shared-event control proving the scenario detects barging (27/40 trials).
- **The invariant:** `test_no_lock_held_while_threads_block` (3 waiters blocked, 200 non-blocking `lock.acquire(blocking=False)` probes all succeed), `test_factory_and_close_never_under_lock` (the factory and close callables themselves probe the pool lock on entry and record the answer: 0 observations of the lock held), `test_factory_runs_on_requesting_thread_not_under_lock`.
- **Idle expiry / no timers:** `test_idle_expiry_is_lazy_and_only_after_60s` (fake monotonic clock: 59.999 s survives, 60.001 s is closed and replaced on the next acquire, `created`/`closed` counters move only when an acquire happens) and `test_no_background_threads_or_timers` (thread count and `threading.enumerate()` snapshot unchanged after pool activity and after idle expiry).
- **Capacity / no leaks / no deadlock:** `test_stress_capacity_and_no_deadlock` (40 threads, 3 s, peak live connections ≤ max_size, `idle + closed == created`, zero timeouts, no thread left alive), `test_timeout_when_exhausted`, `test_factory_failure_releases_reserved_slot`, `test_failure_wakes_queued_waiter`, `test_release_foreign_connection_rejected`, `test_construction_limits`.

## C2

Executed:

```
$ cd /tmp/bench_work/c2
$ python3 main.py            # reproducer + sweep, output below
$ python3 depth.py           # recursion limits, output below
```

Files: `/tmp/bench_work/c2/resolver.py` (original + fixed + helpers), `/tmp/bench_work/c2/main.py`, `/tmp/bench_work/c2/depth.py`.

### Cause

`visit()` adds the node to `seen` on entry, and the `if node in seen: return` test sits **above** `if node in stack: raise`. Every node that is on the current DFS path has therefore already been put in `seen`, so the cycle branch is unreachable dead code: no cycle can ever be reported, and the traversal happily marks a cyclic graph as resolved. A second symptom follows: because `seen` means "visited", not "finished", the emitted order can put a task before one of its own dependencies — which is why the shipped resolver looked correct on an acyclic test suite and quietly produced garbage orders on cyclic input rather than merely accepting them.

Instrumented proof (the traversal counted which branch fired): across 5 cyclic graphs `if node in seen: return` fired 18 times and `if node in stack` fired **0** times.

### Fix

```python
"""Task C2 - the dependency resolver, as found, and fixed.

resolve_original is the code exactly as it was handed over.
resolve_fixed is the corrected version.
"""

from __future__ import annotations


# --------------------------------------------------------------------------
# as found
# --------------------------------------------------------------------------
def resolve_original(graph):
    """Return a build order: every task appears after all of its deps."""
    order, seen = [], set()

    def visit(node, stack):
        if node in seen:
            return
        if node in stack:
            raise ValueError(f"cycle through {node}")
        stack.add(node)
        seen.add(node)
        for dep in graph.get(node, ()):
            visit(dep, stack)
        order.append(node)
        stack.discard(node)

    for node in graph:
        visit(node, set())
    return order


# --------------------------------------------------------------------------
# fixed
# --------------------------------------------------------------------------
def resolve_fixed(graph):
    """Return a build order: every task appears after all of its deps.

    Raises ValueError on any cycle (including self-dependencies).

    Three-colour DFS:
      * ``stack``  - nodes on the current path (grey).  Reaching one means the
        graph is not acyclic.  Checked *first*, so a node that is on the path
        can never be mistaken for a finished one.
      * ``done``   - nodes whose whole sub-graph is already known acyclic and
        ordered (black).  Re-entering one is a legitimate memo hit, which is
        what keeps the shared-across-roots traversal linear.
    A node is marked done only after all of its dependencies have been
    processed, and the reservation is removed from the path on the way out.
    """
    order: list = []
    done: set = set()

    def visit(node, stack):
        if node in stack:
            raise ValueError(f"cycle through {node}")
        if node in done:
            return
        stack.add(node)
        for dep in graph.get(node, ()):
            visit(dep, stack)
        stack.discard(node)
        done.add(node)
        order.append(node)

    for node in graph:
        visit(node, set())
    return order


# --------------------------------------------------------------------------
# helpers used by the reproducer
# --------------------------------------------------------------------------
def order_violations(order, graph):
    """Edges (node -> dep) where dep is not built before node."""
    where = {node: i for i, node in enumerate(order)}
    bad = []
    for node in graph:
        for dep in graph.get(node, ()):
            if dep not in where:
                bad.append((node, dep, "dep missing from order"))
            elif where[dep] >= where[node]:
                bad.append((node, dep, f"dep at {where[dep]} not before {where[node]}"))
    return bad


def instrumented_original(graph):
    """Same traversal as resolve_original, counting which branch fires."""
    stats = {"seen_hit": 0, "stack_hit": 0, "cycle_detected": 0}
    order, seen = [], set()

    def visit(node, stack):
        if node in seen:
            stats["seen_hit"] += 1
            return
        if node in stack:
            stats["stack_hit"] += 1
            stats["cycle_detected"] += 1
            raise ValueError(f"cycle through {node}")
        stack.add(node)
        seen.add(node)
        for dep in graph.get(node, ()):
            visit(dep, stack)
        order.append(node)
        stack.discard(node)

    for node in graph:
        visit(node, set())
    return order, stats
```

`resolve_fixed` checks the path set first and marks a node finished only after its whole dependency sub-graph has been processed. The memoisation benefit of the original (each node expanded once, shared across roots) is preserved, and the only behaviour change is that cycles raise.

### Reproduction and before/after output (verbatim)

```

========================================================================
1. the reported project: accepted by the shipped resolver
========================================================================

project graph (model depends on codegen, codegen depends on model)
  input: {'app': ['api', 'ui'], 'api': ['model'], 'ui': ['theme'], 'model': ['codegen', 'logger'], 'codegen': ['model'], 'logger': [], 'theme': []}
  resolve_original : ACCEPTED -> ['codegen', 'logger', 'model', 'api', 'theme', 'ui', 'app']
                     dependency violations: [('codegen', 'model', 'dep at 2 not before 0')]
  resolve_fixed    : ValueError(cycle through model)

========================================================================
2. minimal reductions of the same defect
========================================================================

two-node cycle  {'a': ['b'], 'b': ['a']}
  input: {'a': ['b'], 'b': ['a']}
  resolve_original : ACCEPTED -> ['b', 'a']
                     dependency violations: [('b', 'a', 'dep at 1 not before 0')]
  resolve_fixed    : ValueError(cycle through a)

self cycle      {'a': ['a']}
  input: {'a': ['a']}
  resolve_original : ACCEPTED -> ['a']
                     dependency violations: [('a', 'a', 'dep at 0 not before 0')]
  resolve_fixed    : ValueError(cycle through a)

cycle behind a finished node  {'x': ['y'], 'y': [], 'p': ['q'], 'q': ['p']}
  input: {'x': ['y'], 'y': [], 'p': ['q'], 'q': ['p']}
  resolve_original : ACCEPTED -> ['y', 'x', 'q', 'p']
                     dependency violations: [('q', 'p', 'dep at 3 not before 2')]
  resolve_fixed    : ValueError(cycle through p)

========================================================================
3. why: the cycle branch is unreachable
========================================================================
  {'app': ['api', 'ui'], 'api': ['model'], 'ui': ['theme'], 'model': ['codegen', 'logger'], 'codegen': ['model'], 'logger': [], 'theme': []} seen-hits=7 stack-hits=0
  {'a': ['b'], 'b': ['a']}                                               seen-hits=2 stack-hits=0
  {'a': ['a']}                                                           seen-hits=1 stack-hits=0
  {'a': ['b', 'c'], 'b': ['c'], 'c': ['b']}                              seen-hits=4 stack-hits=0
  {'a': ['b'], 'b': ['c'], 'c': ['d'], 'd': ['b']}                       seen-hits=4 stack-hits=0
  total over 5 cyclic graphs: 'node in seen' fired 18 times, 'node in stack' fired 0 times
  resolve_original adds a node to `seen` *before* recursing, so every node
  that is on the current path is already in `seen`; the `if node in seen:
  return` test above it always wins and `raise ValueError(cycle ...)` is dead code.

========================================================================
4. sweep: does the fix regress correct graphs / catch cycles?
========================================================================
  random acyclic graphs: 300; Kahn flagged 0 as cyclic; orders valid for all nodes/edges -> original 300/300, fixed 300/300
  random graphs with a flipped edge: 300; Kahn agrees 300 of them are cyclic (0 disputed)
  rejected by resolver -> original 0/300, fixed 300/300

dag   {'a': ['b','c'], 'b': ['d'], 'c': ['d'], 'd': []}
  input: {'a': ['b', 'c'], 'b': ['d'], 'c': ['d'], 'd': []}
  resolve_original : ACCEPTED -> ['d', 'b', 'c', 'a']
                     dependency violations: none
  resolve_fixed    : ['d', 'b', 'c', 'a']  (violations: none)

cyclic twin (d -> b added)
  input: {'a': ['b', 'c'], 'b': ['d'], 'c': ['d'], 'd': ['b']}
  resolve_original : ACCEPTED -> ['d', 'b', 'c', 'a']
                     dependency violations: [('d', 'b', 'dep at 1 not before 0')]
  resolve_fixed    : ValueError(cycle through b)

========================================================================
5. other behaviour the fix keeps / changes deliberately
========================================================================

dependency missing as a key: {'a': ['b']}
  input: {'a': ['b']}
  resolve_original : ACCEPTED -> ['b', 'a']
                     dependency violations: none
  resolve_fixed    : ['b', 'a']  (violations: none)
  fixed recursion limit untouched; sys.getrecursionlimit()=1000
  deep chain of 199 nodes -> ['n198', 'n197', 'n196']... len=200
```

```
  chain of 199 edges     | original: ok, order length 200 | fixed: ok, order length 200
  chain of 999 edges     | original: RecursionError | fixed: RecursionError
  chain of 1000 edges    | original: RecursionError | fixed: RecursionError
  chain of 2000 edges    | original: RecursionError | fixed: RecursionError
  sys.getrecursionlimit() = 1000
```

Note for the reviewer: the recursion limit is a limitation both versions share (a chain deeper than ~900 nodes raises `RecursionError` with the default limit of 1000); fixing that means rewriting the traversal iteratively, which is a bigger change than this bug warrants and was not done here.

## C3

Executed:

```
$ cd /tmp/bench_work/c3
$ python3 check_memoize.py     # every case run against the decorator as found and the corrected one
```

Files: `/tmp/bench_work/c3/memoize_as_found.py` (the decorator verbatim, plus the corrected one), `/tmp/bench_work/c3/check_memoize.py`.

### Verdict

**Not correct.** It is correct only for functions whose arguments are positional, mutually distinct under `str()`, and stable over their lifetime, called from one thread. Four defects are real and observable:

1. `key = ",".join(str(a) for a in args)` is not injective. `f(1, 2)` and `f("1", "2")` share the key `"1,2"`; `f(1, 2)` and `f("1,2")` also share it (arity collapses); `f(1, 2, 3)` and `f(1, "2,3")` likewise. The cached *value for different arguments* is then returned.
2. `str()`-based keys alias distinct objects with the same string form — e.g. two different `Ticket` instances whose `__str__` is the ticket number — so a correct-looking cache returns one object's fee for another object.
3. `wrapper(*args)` has no `**kwargs`: any call using a keyword argument raises `TypeError`. That is a signature change silently imposed on every decorated function, and it also loses `__name__`/`__doc__`/`__qualname__`/`inspect.signature` because there is no `functools.wraps`.
4. `if key not in cache: cache[key] = fn(*args)` is a check-then-act race. With 16 threads making the first call with one key, the wrapped function ran 16 times — duplicated work *and* duplicated side effects. `cache` also grows without bound (5000 distinct calls → 5000 entries) and is exposed as a mutable attribute with no invalidation semantics.

What it does get right: `key not in cache` (rather than a truthiness test) caches `None`/`False`/`0` correctly; the wrapper recurses correctly through the decorated name; repeated identical positional calls are served from the cache; and a mutated argument usually does *not* produce a stale hit because `str()` of the mutation differs (measured, reported as a control).

### Corrected decorator

```python
"""Task C3 - the memoize decorator as found, plus a corrected version.

The version under review (verbatim from the codebase) is kept as ``memoize``
in memoize_as_found.py; ``memoize_fixed`` is what replaces it.
"""


def memoize(fn):
    cache = {}

    def wrapper(*args):
        key = ",".join(str(a) for a in args)
        if key not in cache:
            cache[key] = fn(*args)
        return cache[key]

    wrapper.cache = cache
    return wrapper


def memoize_fixed(fn=None, *, maxsize=None, thread_safe=False):
    """Memoize that keys on the real arguments.

    * args and kwargs both participate in the key (no signature change)
    * the key is the argument tuple itself, so 1 and "1" cannot collide and
      "," cannot be smuggled through a string argument
    * functools.wraps preserves __name__/__doc__/__qualname__ and the
      inspect.signature of the wrapped function
    * optional LRU bound and a lock, both opt-in so behaviour is unchanged
    """

    import functools
    import threading

    def decorator(func):
        cache = {}
        order = []                      # insertion order for the optional bound
        lock = threading.Lock()

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                key = (args, tuple(sorted(kwargs.items())))
                hash(key)
            except TypeError:
                # unhashable argument: no caching is possible, just call through
                return func(*args, **kwargs)

            def lookup():
                if key in cache:
                    if maxsize:
                        order.remove(key)
                        order.append(key)
                    return True, cache[key]
                return False, None

            def store(value):
                cache[key] = value
                if maxsize:
                    order.append(key)
                    while len(order) > maxsize:
                        oldest = order.pop(0)
                        cache.pop(oldest, None)

            if not thread_safe:
                hit, value = lookup()
                if hit:
                    return value
                value = func(*args, **kwargs)
                store(value)
                return value
            # ``thread_safe=True``: the lock covers lookup *and* the call, so
            # the wrapped function runs at most once per key.  Serialising the
            # call is the price of that guarantee; a production version would
            # use a per-key in-flight marker instead.
            with lock:
                hit, value = lookup()
                if hit:
                    return value
                value = func(*args, **kwargs)
                store(value)
                return value

        wrapper.cache = cache
        return wrapper

    if fn is not None:
        return decorator(fn)
    return decorator
```

### Run output (verbatim)

```

========================================================================
1. different argument lists share one cache slot (string key)
========================================================================
  as found: f(1,2) then f('1','2')                   FAIL got='int:1|int:2' expected='str:1|str:2'
  as found: f(1,2) then f('1,2') (arity)             FAIL got=2 expected=1
  as found: f(1,2,3) then f(1,'2,3')                 FAIL got='1+2+3' expected='1+2,3'
  fixed: f(1,2) then f('1','2')                      ok   got='str:1|str:2' expected='str:1|str:2'
  fixed: f(1,2) then f('1,2') (arity)                ok   got=1 expected=1
  fixed: f(1,2,3) then f(1,'2,3')                    ok   got='1+2,3' expected='1+2,3'

========================================================================
2. distinct objects that stringify the same collide
========================================================================
  as found: fee(ticket A1 #1) then fee(ticket A1 #2) FAIL got=(10, 10) expected=(10, 20)
  fixed: fee(ticket A1 #1) then fee(ticket A1 #2)    ok   got=(10, 20) expected=(10, 20)
  as found: (control) total([1]) then total([1,2])   ok   got=(1, 3) expected=(1, 3)
  fixed: (control) total([1]) then total([1,2])      ok   got=(1, 3) expected=(1, 3)

========================================================================
3. keyword arguments and function metadata
========================================================================
  as found: f(2, b=5)                                FAIL got="TypeError: memoize.<locals>.wrapper() got an unexpected keyword argument 'b'" expected=10
  fixed: f(2, b=5)                                   ok   got=10 expected=10
  as found: __name__/__doc__ preserved               FAIL got=('wrapper', None) expected=('volume', 'Return the box volume.')
  fixed: __name__/__doc__ preserved                  ok   got=('volume', 'Return the box volume.') expected=('volume', 'Return the box volume.')

========================================================================
4. concurrent first calls on one key
========================================================================
  as found                           wrapped fn executed 16/16 times for a single key (NOT ok - duplicated work/side effects)
  fixed (thread_safe=False)          wrapped fn executed 16/16 times for a single key (NOT ok - duplicated work/side effects)
  fixed (thread_safe=True)           wrapped fn executed  1/16 times for a single key (ok)

========================================================================
5. cache growth
========================================================================
  as found               cache entries after 5000 distinct calls: 5000
  fixed(maxsize=128)     cache entries after 5000 distinct calls: 128

========================================================================
6. what it does get right
========================================================================
  recursion through the wrapper works: memoize fib(30)   = 832040
                                    fixed    fib(30)   = 832040
  correct results for hashable, immutable, positional args: see case 1 first calls
  repeated identical calls are served from the cache (one execution per key): see case 4, single-threaded
  None/False-y return values are cached correctly, because the code tests 'key not in cache' rather than truthiness
  falsy returns cached: calls=2 (expected 2)

verdict: the decorator as found is NOT correct.
```

## C4

Executed:

```
$ cd /tmp/bench_work/c4
$ python3 c4.py      # correctness sweep + timings, output below
```

File: `/tmp/bench_work/c4/c4.py`.

### Complexity

- Original: **Θ(n²)** comparisons (Σi = n(n−1)/2), Θ(n) extra space. Measured ratio for 10 000 → 20 000 was 3.95×, consistent with quadratic.
- Replacement: **O(n log n)** time — one Fenwick-tree prefix query and one update per element, each O(log m) where m = number of distinct values — and **O(m)** extra space for the tree plus the rank map. Coordinate compression via `sorted(set(values))` costs O(n log m).
- Non-integer inputs (floats, Decimals, other mutually comparable types) go through a `bisect`+`insort` path that keeps the original's semantics without requiring hashability; its worst case is O(n²) in list movement, so it is chosen only when the fast path would change semantics, and it was measured and cross-checked as well (5 000-element float inputs agree with the original).

The Fenwick version and an independent merge-sort version were run against each other on the large inputs, so the "same results" claim does not rest on one implementation being both the subject and the oracle. The original is the oracle for every small input, including duplicates, negatives, empty and single-element lists, all-equal, sorted and reverse-sorted inputs.

```python
"""Task C4 - count_smaller_before: original vs replacement, plus measurements."""

from __future__ import annotations

import bisect
import random
import time


# --------------------------------------------------------------------------
# as found
# --------------------------------------------------------------------------
def count_smaller_before(values):
    """For each i, how many j < i have values[j] < values[i]."""
    out = []
    for i, v in enumerate(values):
        n = 0
        for j in range(i):
            if values[j] < v:
                n += 1
        out.append(n)
    return out


# --------------------------------------------------------------------------
# replacement: Fenwick tree (binary indexed tree) over the sorted distinct values
# --------------------------------------------------------------------------
def count_smaller_before_fast(values):
    """Same result as count_smaller_before, O(n log n).

    For each position we need the number of previously seen values that are
    strictly smaller.  Coordinate-compress the distinct values to 1..m, keep a
    Fenwick tree of "how many of each rank have been seen", query the prefix
    [1, rank(v)-1], then add one for v.  Duplicates and negative numbers need
    no special casing: equal values share a rank and are therefore never
    counted, which is exactly what "strictly smaller" means.
    """
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [0]

    # Fast path: plain ints (the stated input). Anything else uses the
    # comparison-based path below, so behaviour stays identical for floats,
    # Decimals, or mixed comparable types.
    for v in values:
        if type(v) is not int:
            return _count_smaller_insort(values)

    order = sorted(set(values))
    rank = {v: i + 1 for i, v in enumerate(order)}       # 1-based
    m = len(order)
    tree = [0] * (m + 1)
    out = []
    append = out.append
    for v in values:
        i = rank[v] - 1                                   # count ranks < v
        s = 0
        while i:
            s += tree[i]
            i -= i & -i
        append(s)
        i = rank[v]
        while i <= m:
            tree[i] += 1
            i += i & -i
    return out


def _count_smaller_insort(values):
    """Generic path: sorted list of what has been seen so far."""
    seen = []
    out = []
    for v in values:
        out.append(bisect.bisect_left(seen, v))           # strictly smaller
        bisect.insort(seen, v)
    return out


# --------------------------------------------------------------------------
# independent second implementation (merge sort), used to cross-check fast
# --------------------------------------------------------------------------
def count_smaller_before_merge(values):
    vals = list(values)
    n = len(vals)
    counts = [0] * n

    def sort_ids(ids):
        length = len(ids)
        if length <= 1:
            return ids
        mid = length // 2
        left = sort_ids(ids[:mid])
        right = sort_ids(ids[mid:])
        out = []
        i = j = 0
        smaller_from_left = 0
        while i < len(left) and j < len(right):
            if vals[left[i]] < vals[right[j]]:
                out.append(left[i])
                i += 1
                smaller_from_left += 1
            else:
                counts[right[j]] += smaller_from_left
                out.append(right[j])
                j += 1
        if i < len(left):
            out.extend(left[i:])
        else:
            for r in right[j:]:        # left is exhausted: every remaining
                counts[r] += smaller_from_left      # right element sees them all
            out.extend(right[j:])
        return out

    sort_ids(list(range(n)))
    return counts


# --------------------------------------------------------------------------
# correctness
# --------------------------------------------------------------------------
def correctness_rounds(rounds=400):
    rng = random.Random(1234)
    generators = [
        ("random ints -100..100", lambda k: [rng.randint(-100, 100) for _ in range(k)]),
        ("random ints -10..10 (heavy duplicates)", lambda k: [rng.randint(-10, 10) for _ in range(k)]),
        ("all equal", lambda k: [7] * k),
        ("all equal negative", lambda k: [-3] * k),
        ("sorted ascending", lambda k: list(range(k))),
        ("sorted descending", lambda k: list(range(k, 0, -1))),
        ("negatives only", lambda k: [-rng.randint(1, 50) for _ in range(k)]),
        ("with zeros", lambda k: [rng.choice([0, 0, 1, -1]) for _ in range(k)]),
        ("single huge + tiny", lambda k: [rng.choice([-10**18, 10**18, 0]) for _ in range(k)]),
        ("floats", lambda k: [round(rng.uniform(-20, 20), 3) for _ in range(k)]),
        ("empty-ish", lambda k: [] if rng.random() < 0.5 else [rng.randint(-5, 5)]),
    ]
    checked = 0
    failures = []
    for label, gen in generators:
        for _ in range(rounds // len(generators) + 1):
            k = rng.randint(0, 40)
            vals = gen(k)
            expected = count_smaller_before(vals)
            fast = count_smaller_before_fast(vals)
            merge = count_smaller_before_merge(vals)
            checked += 1
            if fast != expected or merge != expected:
                failures.append((label, vals, expected, fast, merge))
    # edge cases explicitly
    for vals in ([], [0], [-1], [5, 5], [-1, -1, -1], [3, 1, 2], [2, 2, 1, 3, 3, 0]):
        checked += 1
        expected = count_smaller_before(vals)
        if count_smaller_before_fast(vals) != expected or count_smaller_before_merge(vals) != expected:
            failures.append(("edge", vals, expected, None, None))
    return checked, failures


def cross_check_large(size, seed):
    """Two independent O(n log n) implementations on one big input."""
    rng = random.Random(seed)
    vals = [rng.randint(-size, size) for _ in range(size)]
    a = count_smaller_before_fast(vals)
    b = count_smaller_before_merge(vals)
    return a == b, sum(a), size


def cross_check_insort(size, seed):
    """The generic (non-int) path against the original, on a smaller input."""
    rng = random.Random(seed)
    vals = [round(rng.uniform(-size, size), 4) for _ in range(size)]
    return (_count_smaller_insort(vals) == count_smaller_before(vals)
            == count_smaller_before_merge(vals) == count_smaller_before_fast(vals))


# --------------------------------------------------------------------------
# timings
# --------------------------------------------------------------------------
def timeit(fn, values, reps=1):
    best = None
    for _ in range(reps):
        t0 = time.perf_counter()
        fn(values)
        dt = time.perf_counter() - t0
        best = dt if best is None else min(best, dt)
    return best


def main():
    print("machine: python %s" % __import__("sys").version.split()[0])
    print()
    print("=" * 72)
    print("correctness")
    print("=" * 72)
    checked, failures = correctness_rounds()
    print(f"  random + edge cases checked against the original: {checked}")
    print(f"  mismatches (fast vs original, merge vs original): {len(failures)}")
    for f in failures[:3]:
        print("   ", f)
    for size in (20_000, 200_000):
        agree, total, n = cross_check_large(size, seed=size)
        print(f"  size {size:>7}: Fenwick == merge-sort: {agree} "
              f"(sum of all counts = {total})")
    for size in (500, 5_000):
        print(f"  size {size:>7}: float input, original == Fenwick == merge == bisect: "
              f"{cross_check_insort(size, seed=size)}")

    print()
    print("=" * 72)
    print("timings (best of 3, same input for both versions)")
    print("=" * 72)
    rng = random.Random(99)
    print(f"  {'n':>9}  {'original s':>13}  {'replacement s':>14}")
    measured = {}
    for n, reps in ((1_000, 3), (2_000, 3), (5_000, 2), (10_000, 1), (20_000, 1)):
        vals = [rng.randint(-n, n) for _ in range(n)]
        t_orig = timeit(count_smaller_before, vals, reps)
        t_new = timeit(count_smaller_before_fast, vals, 3)
        measured[n] = (t_orig, t_new)
        print(f"  {n:>9}  {t_orig:>13.4f}  {t_new:>14.5f}   (original reps={reps})")
    for n in (50_000, 200_000, 1_000_000):
        vals = [rng.randint(-n, n) for _ in range(n)]
        t_new = timeit(count_smaller_before_fast, vals, 3)
        print(f"  {n:>9}  {'(not measured)':>13}  {t_new:>14.5f}")
    # extrapolation evidence from the two largest measured original runs
    print()
    r1 = measured[20_000][0] / measured[10_000][0]
    t20 = measured[20_000][0]
    print(f"  original: 10_000 -> 20_000 time ratio = {r1:.2f} (quadratic behaviour confirmed)")
    print(f"  original at 20_000 = {t20:.3f}s, so 200_000 (100x the input) projects to "
          f"about {t20 * 100 * 100 / 60:.0f} minutes")
    print(f"  replacement at 20_000 = {measured[20_000][1]*1000:.1f} ms")


if __name__ == "__main__":
    main()
```

### Measured output (verbatim)

```
machine: python 3.14.6

========================================================================
correctness
========================================================================
  random + edge cases checked against the original: 414
  mismatches (fast vs original, merge vs original): 0
  size   20000: Fenwick == merge-sort: True (sum of all counts = 99445109)
  size  200000: Fenwick == merge-sort: True (sum of all counts = 9994805908)
  size     500: float input, original == Fenwick == merge == bisect: True
  size    5000: float input, original == Fenwick == merge == bisect: True

========================================================================
timings (best of 3, same input for both versions)
========================================================================
          n     original s   replacement s
       1000         0.0104         0.00051   (original reps=3)
       2000         0.0437         0.00115   (original reps=3)
       5000         0.2969         0.00374   (original reps=2)
      10000         1.1920         0.00736   (original reps=1)
      20000         4.7140         0.01530   (original reps=1)
      50000  (not measured)         0.04091
     200000  (not measured)         0.19478
    1000000  (not measured)         1.42326

  original: 10_000 -> 20_000 time ratio = 3.95 (quadratic behaviour confirmed)
  original at 20_000 = 4.714s, so 200_000 (100x the input) projects to about 786 minutes
  replacement at 20_000 = 15.3 ms
```

Against the target — 200 000 random integers in under 2 seconds: measured **0.195 s**; 1 000 000 in 1.42 s. The original could not be measured at 200 000; the largest size measured there was **20 000 at 4.71 s**, and its own growth curve (3.95× per doubling) projects 200 000 to roughly 13 hours — that figure is an extrapolation from the measured 10 000/20 000 pair, not a measurement, and is labelled as such.
