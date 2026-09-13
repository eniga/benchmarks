"""A fixed-size, FIFO-fair connection pool.

Invariants (see task C1):
  * No lock is held while calling the user-supplied ``factory`` or ``close``.
  * No lock is held while a thread is blocked waiting for a connection.
  * Waiters are served strictly FIFO.
  * Connections idle for more than ``idle_timeout`` seconds are closed and
    replaced lazily on the next acquire (no background threads or timers).
  * Only the monotonic clock is used.
"""

from __future__ import annotations

import threading
import time


class _Waiter:
    __slots__ = ("event", "conn")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.conn = None


class ConnectionPool:
    def __init__(self, factory, close, max_size, idle_timeout=60.0):
        if max_size < 1:
            raise ValueError("max_size must be >= 1")
        self._factory = factory
        self._close = close
        self._max_size = int(max_size)
        self._idle_timeout = float(idle_timeout)
        self._lock = threading.RLock()
        self._idle: list[tuple[object, float]] = []  # (conn, released_at)
        self._in_use = 0
        self._waiters: list[_Waiter] = []  # FIFO

    # -- internal helpers -------------------------------------------------
    def _live(self) -> int:
        return self._in_use + len(self._idle)

    def _pop_idle(self):
        conn, released_at = self._idle.pop()
        return conn, (time.monotonic() - released_at)

    # -- public API -------------------------------------------------------
    def acquire(self, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            waiter = None
            with self._lock:
                if self._idle:
                    conn, idle_for = self._pop_idle()
                    self._in_use += 1
                    stale = idle_for > self._idle_timeout
                    action = "idle"
                elif self._live() < self._max_size:
                    self._in_use += 1
                    conn = None
                    stale = False
                    action = "create"
                else:
                    waiter = _Waiter()
                    self._waiters.append(waiter)
                    conn = None
                    stale = False
                    action = "wait"

            if action == "wait":
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    with self._lock:
                        self._waiters.remove(waiter)
                    raise TimeoutError("timed out waiting for a connection")
                got = waiter.event.wait(remaining)
                if got:
                    return waiter.conn
                # Timed out, but a release may have raced us. Re-check.
                with self._lock:
                    if waiter.event.is_set():
                        return waiter.conn
                    self._waiters.remove(waiter)
                raise TimeoutError("timed out waiting for a connection")

            if action == "create":
                # No lock held while calling the (possibly blocking) factory.
                return self._factory()

            # action == "idle"
            if stale:
                # No lock held while calling close or the factory.
                self._close(conn)
                return self._factory()
            return conn

    def release(self, conn) -> None:
        with self._lock:
            if self._waiters:
                # Hand straight to the head waiter. The connection stays
                # checked out (now owned by the waiter), so _in_use is
                # unchanged.
                waiter = self._waiters.pop(0)  # head of the FIFO
                waiter.conn = conn
                waiter.event.set()
                return
            self._in_use -= 1
            self._idle.append((conn, time.monotonic()))


# Expose the internal lock for invariant testing.
def _lock_held(pool: ConnectionPool) -> bool:
    # Try a non-blocking acquire; if we get it, the lock was free.
    acquired = pool._lock.acquire(blocking=False)
    if acquired:
        pool._lock.release()
    return not acquired
