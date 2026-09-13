"""Negative control for the FIFO tests: does the test actually catch barging?

NaivePool has the same API as pool.ConnectionPool but uses a plain
threading.Condition (notify, no explicit queue).  Running the same
"late arrival must not take a connection ahead of a longer-waiting thread"
scenario against it shows whether the FIFO test is capable of failing.
"""

from __future__ import annotations

import threading
import time


class NaivePool:
    def __init__(self, max_size, factory, close):
        self._max = max_size
        self._factory = factory
        self._close = close
        self._idle = []
        self._in_use = 0
        self._cond = threading.Condition()
        self._lock = threading.Lock()   # only so the probe in tests has a target

    def counts(self):
        with self._cond:
            return {"waiting": -1, "idle": len(self._idle), "leased": self._in_use,
                    "creating": 0, "handed": 0, "created": 0, "closed": 0}

    def acquire(self, timeout=None):
        with self._cond:                      # lock held while waiting: Condition.wait
            while not self._idle and self._in_use >= self._max:
                if not self._cond.wait(timeout):
                    raise TimeoutError("no connection")
            if self._idle:
                conn = self._idle.pop(0)
            else:
                self._in_use += 1
                conn = self._factory()
            return conn

    def release(self, conn):
        with self._cond:
            self._idle.append(conn)
            self._cond.notify()               # wakes an arbitrary waiter


def scenario(pool_factory, trials=20):
    violations = 0
    orders = []
    for _ in range(trials):
        pool = pool_factory()
        holder = pool.acquire()
        served = []

        def worker(i):
            conn = pool.acquire(timeout=5)
            served.append(f"w{i}")
            time.sleep(0.005)
            pool.release(conn)

        for i in range(4):
            threading.Thread(target=worker, args=(i,), name=f"w{i}").start()
            time.sleep(0.05)                  # let them queue in this order

        def late():
            conn = pool.acquire(timeout=5)
            served.append("late")
            pool.release(conn)

        threading.Thread(target=late, name="late").start()
        time.sleep(0.05)
        pool.release(holder)
        time.sleep(0.4)
        orders.append(served)
        if served != ["w0", "w1", "w2", "w3", "late"]:
            violations += 1
    return violations, orders


if __name__ == "__main__":
    v, orders = scenario(lambda: NaivePool(1, lambda: object(), lambda c: None))
    print(f"Condition-based pool: {v}/20 trials served out of FIFO order")
    for i, o in enumerate(orders):
        print(f"  trial {i}: {o}")
