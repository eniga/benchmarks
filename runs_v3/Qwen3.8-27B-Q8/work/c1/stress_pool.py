"""Stress test: many threads hammer a small pool. Verifies no deadlock, no
connection leak, no invariant violation, and that the pool never exceeds
max_size live connections."""
import threading
import time
from pool import ConnectionPool


def main():
    max_size = 4
    created = 0
    closed = 0
    created_lock = threading.Lock()
    violations = []

    def factory():
        nonlocal created
        if not pool._lock.acquire(blocking=False):
            violations.append("factory held lock")
        else:
            pool._lock.release()
        with created_lock:
            created += 1
        time.sleep(0.0005)  # simulate I/O
        return object()

    def close(conn):
        nonlocal closed
        if not pool._lock.acquire(blocking=False):
            violations.append("close held lock")
        else:
            pool._lock.release()
        with created_lock:
            closed += 1
        time.sleep(0.0005)

    pool = ConnectionPool(factory=factory, close=close, max_size=max_size,
                          idle_ttl=0.02)

    errors = []
    stop = threading.Event()

    def worker():
        try:
            for _ in range(300):
                c = pool.acquire(timeout=2.0)
                time.sleep(0.0003)  # hold briefly
                pool.release(c)
        except Exception as e:  # noqa
            errors.append(repr(e))

    threads = [threading.Thread(target=worker) for _ in range(16)]
    t0 = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    elapsed = time.monotonic() - t0

    alive = [t for t in threads if t.is_alive()]
    assert not alive, f"{len(alive)} workers deadlocked"
    assert not errors, f"errors: {errors[:5]}"
    assert not violations, f"invariant violations: {violations[:5]}"
    # At quiescence every connection is idle, so live == idle and the number
    # of never-closed connections must equal the idle count (a real leak would
    # show up as live > max_size or created-closed > max_size).
    live = pool.live_count()
    assert 0 <= live <= max_size, f"live out of bounds: {live}"
    assert created - closed == live, (
        f"leak: created={created} closed={closed} live={live}")
    print(f"STRESS OK: {len(threads)} workers x 300 ops in {elapsed:.2f}s, "
          f"created={created}, closed={closed}, live={live}")


if __name__ == "__main__":
    main()
