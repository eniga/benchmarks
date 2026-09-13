"""A bounded, FIFO-fair connection pool.

Design notes (each requirement maps to a mechanism):

* Fixed maximum size -- ``self._max`` bounds ``self._count`` (live connections).
* Lazy replacement of idle connections -- ``_grab`` purges idle entries whose
  idle-time exceeds ``IDLE_TTL`` using ``time.monotonic`` and closes them; no
  background thread or timer ever exists.
* FIFO fairness -- a single deque of waiters (``self._waiters``) is the only
  ordering authority. ``release`` hands a connection to the *front* waiter and
  ``acquire`` never lets a newly arriving thread claim a connection that a
  queued waiter is entitled to (an idle connection only exists when there are
  no waiters, so a late arrival cannot steal it).
* Monotonic clock only -- every timestamp comes from ``time.monotonic``.
* Caller-supplied factory/close -- ``factory`` and ``close`` are invoked only
  while ``self._lock`` is NOT held (see below), and either may block on I/O.
* No lock held while calling factory/close -- creation and closing happen
  outside the ``with self._lock`` block.
* No lock held while blocked waiting -- ``waiter.event.wait`` is called while
  ``self._lock`` is released.

``self._lock`` is a plain (non-reentrant) ``threading.Lock``; every helper that
assumes the lock is already held is suffixed ``_locked`` and must not re-acquire
it.
"""

from __future__ import annotations

import threading
import time
from collections import deque


class _Waiter:
    """A single queued ``acquire`` call. ``conn`` is set by the winner only."""

    __slots__ = ("event", "conn")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.conn = None


class ConnectionPool:
    def __init__(self, factory, close, max_size, idle_ttl=60.0):
        if max_size < 1:
            raise ValueError("max_size must be >= 1")
        self._factory = factory
        self._close = close
        self._max = max_size
        self._idle_ttl = float(idle_ttl)

        self._lock = threading.Lock()
        self._idle: deque = deque()      # [conn, idle_since]
        self._active: set = set()        # connections currently checked out
        self._waiters: deque = deque()   # FIFO of _Waiter
        self._count = 0                  # live connections (active + idle)

    # -- internal helpers that assume the lock is held ---------------------
    def _purge_expired_locked(self):
        """Drop idle connections older than the TTL; return the dead ones."""
        dead = []
        now = time.monotonic()
        while self._idle:
            conn, idle_since = self._idle.popleft()
            if now - idle_since > self._idle_ttl:
                dead.append(conn)
                self._count -= 1
            else:
                # still usable: put it back for the caller to hand out
                self._idle.appendleft([conn, idle_since])
                break
        return dead

    def _try_idle_locked(self):
        """Return a fresh idle connection (or None). Assumes lock held."""
        while self._idle:
            conn, idle_since = self._idle.popleft()
            if time.monotonic() - idle_since > self._idle_ttl:
                self._count -= 1
                continue
            self._active.add(conn)
            return conn
        return None

    # -- public API --------------------------------------------------------
    def acquire(self, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            # 1) Grab a fresh idle connection, purging expired ones first.
            dead = []
            create_needed = False
            with self._lock:
                dead = self._purge_expired_locked()
                conn = self._try_idle_locked()
                if conn is not None:
                    return conn
                create_needed = self._count < self._max
            for d in dead:
                self._safe_close(d)
            if create_needed:
                # Create OUTSIDE the lock (factory may block on I/O).
                try:
                    conn = self._factory()
                except BaseException:
                    with self._lock:
                        self._count -= 1
                    raise
                with self._lock:
                    self._active.add(conn)
                    self._count += 1
                return conn

            # 2) At capacity: queue FIFO and wait OUTSIDE the lock.
            waiter = _Waiter()
            with self._lock:
                self._waiters.append(waiter)
            while True:
                with self._lock:
                    if waiter.conn is not None:
                        return waiter.conn
                    if deadline is None:
                        remaining = None
                    else:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            if waiter in self._waiters:
                                self._waiters.remove(waiter)
                            raise TimeoutError(
                                f"acquire timed out after {timeout}s"
                            )
                if remaining is not None and remaining <= 0:
                    if waiter in self._waiters:
                        self._waiters.remove(waiter)
                    raise TimeoutError(f"acquire timed out after {timeout}s")
                waiter.event.wait(timeout=remaining)

    def release(self, conn):
        with self._lock:
            if conn not in self._active:
                # Not currently owned by us (already closed / unknown): just
                # close it. Do not touch _count -- it was never counted.
                self._safe_close(conn)
                return
            self._active.discard(conn)
            if self._waiters:
                # Hand the connection straight to the front waiter (FIFO).
                waiter = self._waiters.popleft()
                waiter.conn = conn
                self._active.add(conn)
                waiter.event.set()
            else:
                self._idle.append([conn, time.monotonic()])

    def _safe_close(self, conn):
        try:
            self._close(conn)
        except Exception:
            # A failing close must never break pool bookkeeping.
            pass

    @property
    def size(self):
        with self._lock:
            return self._count

    @property
    def available(self):
        with self._lock:
            return len(self._idle)

    @property
    def active(self):
        with self._lock:
            return len(self._active)
