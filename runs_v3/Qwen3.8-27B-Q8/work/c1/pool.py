"""A fixed-size, FIFO-fair connection pool.

Design notes (mapped to the requirements):

* Fixed maximum size, configurable at construction: ``max_size``.
* ``acquire(timeout)`` hands out a connection or raises ``TimeoutError``.
* ``release(conn)`` returns a connection to the pool.
* Strict FIFO fairness: waiting threads are kept in a deque (``_waiters``) in
  the order they started waiting. A connection that becomes available is always
  handed to ``_waiters.popleft()`` -- the thread that has been waiting longest.
  A thread may only create a new connection (grow the pool) when *no* thread is
  waiting, so a late arrival can never grab a connection ahead of a longer
  waiter.
* Idle connections older than ``idle_ttl`` (default 60 s) are closed lazily the
  next time ``acquire`` pops the idle deque. No background threads or timers.
* Only ``time.monotonic()`` is used for all timing.
* The caller supplies ``factory`` (create) and ``close`` (destroy); both may
  block on I/O.

Invariant maintained throughout:
  * ``self._lock`` is never held while ``factory`` or ``close`` is called.
  * ``self._lock`` is never held while a thread is blocked waiting (waiting is
    done on a per-waiter ``threading.Event``, which does not hold the lock).
"""

from __future__ import annotations

import threading
import time
from collections import deque


class _Waiter:
    __slots__ = ("event", "conn", "name")

    def __init__(self, name=None):
        self.event = threading.Event()
        self.conn = None
        self.name = name


class ConnectionPool:
    def __init__(self, factory, close, max_size, idle_ttl=60.0):
        if max_size < 1:
            raise ValueError("max_size must be >= 1")
        if idle_ttl < 0:
            raise ValueError("idle_ttl must be >= 0")
        self._factory = factory
        self._close = close
        self._max_size = max_size
        self._idle_ttl = idle_ttl

        self._lock = threading.Lock()
        self._idle = deque()      # deque of (conn, returned_at_monotonic)
        self._live = 0            # live connections = idle + checked out
        self._waiters = deque()   # FIFO of _Waiter

    # -- internal helpers (must be called with self._lock held) ---------------

    def _now(self):
        return time.monotonic()

    def _pop_idle_locked(self):
        """Pop a fresh idle connection, collecting stale ones to close.

        Returns ``(conn_or_None, stale_list)``. Stale connections are removed
        from the pool and their live count decremented here, but they are
        closed by the caller *outside* the lock.
        """
        now = self._now()
        stale = []
        while self._idle:
            conn, since = self._idle.popleft()
            if now - since <= self._idle_ttl:
                return conn, stale
            stale.append(conn)
            self._live -= 1
        return None, stale

    def _wake_head_locked(self):
        """Wake the head waiter without handing it a connection.

        Used after a failed creation frees a slot: the woken waiter loops back
        and performs the creation itself.
        """
        if self._waiters:
            self._waiters.popleft().event.set()

    # -- public API -----------------------------------------------------------

    def acquire(self, timeout=None, _waiter_name=None):
        deadline = None
        if timeout is not None:
            deadline = self._now() + timeout

        while True:
            stale = []
            with self._lock:
                conn, stale = self._pop_idle_locked()
                if conn is None:
                    # Only grow the pool if nobody is waiting, so a late
                    # arrival can never take a connection ahead of a waiter.
                    if not self._waiters and self._live < self._max_size:
                        self._live += 1
                        creating = True
                        waiter = None
                    else:
                        creating = False
                        waiter = _Waiter(name=_waiter_name)
                        self._waiters.append(waiter)
            # Close evicted idle connections OUTSIDE the lock.
            for c in stale:
                self._close(c)

            if conn is not None:
                return conn
            if creating:
                # Call the factory OUTSIDE the lock.
                try:
                    return self._factory()
                except BaseException:
                    with self._lock:
                        self._live -= 1
                        self._wake_head_locked()
                    raise

            # Block on a per-waiter Event; the pool lock is NOT held here.
            if deadline is None:
                waiter.event.wait()
            else:
                remaining = deadline - self._now()
                if remaining <= 0:
                    with self._lock:
                        self._remove_waiter(waiter)
                    raise TimeoutError("timed out acquiring a connection")
                if not waiter.event.wait(remaining):
                    with self._lock:
                        handed = waiter.conn
                        if handed is None:
                            self._remove_waiter(waiter)
                    if handed is not None:
                        return handed
                    raise TimeoutError("timed out acquiring a connection")

            conn = waiter.conn
            if conn is not None:
                return conn
            # Woken without a connection (slot freed by a failed creation):
            # loop around and take the slot ourselves.

    def release(self, conn):
        with self._lock:
            if self._waiters:
                waiter = self._waiters.popleft()
                waiter.conn = conn
                waiter.event.set()  # non-blocking; safe under the lock
            else:
                self._idle.append((conn, self._now()))

    def _remove_waiter(self, waiter):
        try:
            self._waiters.remove(waiter)
        except ValueError:
            pass

    # -- introspection helpers used by the test-suite -------------------------

    def waiter_count(self):
        with self._lock:
            return len(self._waiters)

    def live_count(self):
        with self._lock:
            return self._live
