"""Randomized stress test for FIFO fairness.

Each held connection is released ONE AT A TIME; before releasing the next we
wait for exactly one more worker to have been granted a connection. This makes
the observed acquisition order equal the grant order, which the pool hands out
strictly FIFO (release pops the front waiter).

Run: python3 c1_stress.py
"""

import os
import random
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(__file__))
from c1_pool import ConnectionPool  # noqa: E402


def run_once(n_waiters, seed):
    random.seed(seed)
    order_lock = threading.Lock()
    order = []
    gate = threading.Event()
    cv = threading.Condition()  # guards order / grants
    grants = [0]

    def factory():
        time.sleep(0.001)
        return object()

    def close(conn):
        time.sleep(0.001)

    pool = ConnectionPool(factory, close, max_size=n_waiters)
    held = [pool.acquire(timeout=5) for _ in range(n_waiters)]

    reached = [threading.Event() for _ in range(n_waiters)]

    def worker(idx):
        reached[idx].set()
        try:
            conn = pool.acquire(timeout=10)
        except Exception as e:
            with cv:
                order.append(("ERR", idx, type(e).__name__))
                cv.notify_all()
            return
        with cv:
            order.append(idx)
            grants[0] += 1
            cv.notify_all()
        gate.wait(timeout=5)
        pool.release(conn)

    threads = []
    for idx in range(n_waiters):
        t = threading.Thread(target=worker, args=(idx,))
        t.start()
        threads.append(t)
        assert reached[idx].wait(timeout=3)
        for _ in range(3000):
            with pool._lock:
                if len(pool._waiters) == idx + 1:
                    break
            time.sleep(0.001)

    # Release the held connections in a RANDOM order, one at a time, waiting for
    # each grant to be observed before releasing the next.
    random.shuffle(held)
    expected = 0
    for c in held:
        pool.release(c)
        with cv:
            while grants[0] <= expected:
                cv.wait(timeout=5)
            expected += 1

    gate.set()
    for t in threads:
        t.join(timeout=10)

    nums = [x for x in order if isinstance(x, int)]
    if nums != list(range(n_waiters)):
        print("SEED", seed, "n", n_waiters, "order", order)
    assert nums == list(range(n_waiters)), (seed, order)
    return order


if __name__ == "__main__":
    total = 0
    for seed in range(60):
        n = random.Random(seed).randint(2, 10)
        run_once(n, seed)
        total += 1
    print("ALL %d STRESS RUNS PASSED (FIFO preserved)" % total)
