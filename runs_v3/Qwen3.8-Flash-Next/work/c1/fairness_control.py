"""Negative control: can the fairness tests actually fail?

The same churn scenario is run against

  * pool.ConnectionPool      - explicit FIFO waiter queue (the C1 answer), and
  * NaivePool               - the obvious threading.Condition implementation.

A holder of the pool's only connection releases it once, after three waiters
have queued.  Two "jumper" threads are started *after* the waiters queued: they
must therefore be served after all three.  Any jumper appearing between two
waiters in the service order is a fairness violation.
"""

from __future__ import annotations

import threading
import time

from naive_condition_pool import NaivePool
from pool import ConnectionPool


def churn_scenario(pool_factory, trials=40):
    violations = 0
    bad_example = None
    for _ in range(trials):
        pool = pool_factory()
        holder = pool.acquire()
        served = []

        def worker(i):
            conn = pool.acquire(timeout=5)
            served.append(f"w{i}")
            time.sleep(0.002)
            pool.release(conn)

        def jumper(tag):
            conn = pool.acquire(timeout=5)
            served.append(tag)
            pool.release(conn)

        for i in range(3):
            threading.Thread(target=worker, args=(i,), name=f"w{i}").start()
            time.sleep(0.04)                      # let them queue in this order

        for tag in ("J1", "J2"):                  # late arrivals
            threading.Thread(target=jumper, args=(tag,), name=tag).start()
        time.sleep(0.04)

        pool.release(holder)                      # single release, chain begins
        time.sleep(0.35)

        waiters_seen = [s for s in served if s.startswith("w")]
        first_jumper = min([i for i, s in enumerate(served) if s.startswith("J")],
                           default=len(served))
        # violation: a jumper was served before all three queued waiters
        if waiters_seen != ["w0", "w1", "w2"] or first_jumper < len(waiters_seen):
            violations += 1
            bad_example = bad_example or served
    return violations, bad_example


class BargingPool:
    """Deliberately unfair control: waiters block on a shared event and an
    idle connection may be taken by anybody, including a late arrival."""

    def __init__(self, max_size, factory, close):
        self._max = max_size
        self._factory = factory
        self._close = close
        self._idle = []
        self._live = 0
        self._lock = threading.Lock()
        self._event = threading.Event()

    def acquire(self, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            with self._lock:
                if self._idle:                    # no 'are there waiters?' check
                    return self._idle.pop()
                if self._live < self._max:
                    self._live += 1
                    return self._factory()
                event = self._event
            if not event.wait(None if deadline is None else max(0.0, deadline - time.monotonic())):
                raise TimeoutError("no connection")

    def release(self, conn):
        with self._lock:
            self._idle.append(conn)
            self._event.set()                     # wake everybody, race for it
            self._event = threading.Event()


def make_strict():
    return ConnectionPool(1, lambda: object(), lambda c: None)


if __name__ == "__main__":
    for name, factory in (("ConnectionPool (FIFO queue)", make_strict),
                          ("NaivePool (Condition/notify)", lambda: NaivePool(1, lambda: object(), lambda c: None)),
                          ("BargingPool (shared event, no queue)", lambda: BargingPool(1, lambda: object(), lambda c: None))):
        v, example = churn_scenario(factory)
        print(f"{name}: {v}/40 trials violated strict FIFO"
              + (f"   first bad order: {example}" if example else ""))
