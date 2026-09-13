import threading
import time
from pool import ConnectionPool

def test_basic():
    factory_calls = []
    close_calls = []
    def factory():
        factory_calls.append(1)
        return len(factory_calls)
    def closer(conn):
        close_calls.append(conn)
    pool = ConnectionPool(max_size=2, factory=factory, closer=closer)
    a = pool.acquire()
    b = pool.acquire()
    assert a != b
    pool.release(a)
    pool.release(b)
    # Reuse
    c = pool.acquire()
    assert c in (a, b)
    pool.release(c)
    print("test_basic passed")

def test_fifo():
    order = []
    lock = threading.Lock()
    def factory():
        with lock:
            return len(order) + 1
    def closer(conn):
        pass
    pool = ConnectionPool(max_size=1, factory=factory, closer=closer)
    conn = pool.acquire()
    results = []
    def waiter(idx):
        c = pool.acquire()
        with lock:
            results.append((idx, c))
        pool.release(c)
    t1 = threading.Thread(target=waiter, args=(1,))
    t2 = threading.Thread(target=waiter, args=(2,))
    t1.start()
    t2.start()
    time.sleep(0.05)
    # Release to first waiter
    pool.release(conn)
    time.sleep(0.05)
    # Release to second waiter
    # The first waiter should have acquired first
    t1.join()
    t2.join()
    # Check order of acquisition
    assert results[0][0] == 1
    assert results[1][0] == 2
    print("test_fifo passed, order:", results)

def test_timeout():
    def factory():
        return object()
    def closer(conn):
        pass
    pool = ConnectionPool(max_size=1, factory=factory, closer=closer)
    c1 = pool.acquire()
    try:
        pool.acquire(timeout=0.1)
        assert False, "Should have timed out"
    except TimeoutError:
        print("test_timeout passed")
    finally:
        pool.release(c1)

def test_idle_close():
    closed = []
    def factory():
        return object()
    def closer(conn):
        closed.append(conn)
    pool = ConnectionPool(max_size=1, factory=factory, closer=closer)
    c1 = pool.acquire()
    pool.release(c1)
    # Wait >60s simulated by manipulating timestamp
    # Directly modify available timestamp
    with pool.lock:
        conn, _ = pool.available.popleft()
        pool.available.append((conn, time.monotonic() - 61))
    c2 = pool.acquire()
    # The old connection should have been closed and a new one created
    # Since factory creates new object each time, c2 should be different
    assert closed, "Idle connection should be closed"
    print("test_idle_close passed, closed count:", len(closed))

if __name__ == "__main__":
    test_basic()
    test_fifo()
    test_timeout()
    test_idle_close()
    print("All tests passed")
