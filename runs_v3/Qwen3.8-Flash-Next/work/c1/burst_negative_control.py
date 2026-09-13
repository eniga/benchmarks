"""Negative control for test_burst_release_keeps_queue_order.

Replaces ConnectionPool.release with a version that hands the released
connection to the TAIL waiter instead of the head, then runs the real test.
If the test passes against this pool, the test is vacuous.
"""

import test_pool as t
import pool as P


def lifo_release(self, conn):
    with self._lock:
        held = self._leased.get(id(conn))
        if held is not conn:
            raise RuntimeError("release(): connection is not owned by this pool")
        if self._waiters:
            tail = self._waiters.pop()                 # <-- LIFO, deliberately wrong
            tail.conn = conn
            self._handed += 1
            self.last_handoffs.append(tail.ident)
            wake = tail
        else:
            self._leased.pop(id(conn), None)
            self._idle.append([conn, self._clock()])
            wake = None
    if wake is not None:
        wake.event.set()


original = P.ConnectionPool.release
P.ConnectionPool.release = lifo_release
detected = 0
for i in range(3):
    try:
        t.test_burst_release_keeps_queue_order()
        print(f"iteration {i}: LIFO pool PASSED the test -> assertion would be vacuous")
    except AssertionError as exc:
        detected += 1
        print(f"iteration {i}: LIFO pool correctly detected, hand-off order was {exc}")
P.ConnectionPool.release = original
print(f"detected {detected} / 3")
