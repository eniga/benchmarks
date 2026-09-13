"""FIFO-fair connection pool with lazy idle expiry.

Invariants maintained:
  * The user-supplied ``factory`` and ``close`` callables are never invoked
    while the pool's internal lock is held.
  * A thread blocked waiting for a connection never holds the pool's lock.
  * Waiters are served strictly first-come-first-served: a late arrival can
    only create a new connection when no thread is waiting.
"""

from __future__ import annotations

import threading
import time
from collections import deque

__all__ = ["ConnectionPool"]


class ConnectionPool:
    def __init__(self, factory, close, max_size, idle_ttl=60.0, clock=time.monotonic):
        if max_size < 1:
            raise ValueError("max_size must be >= 1")
        self._factory = factory
        self._close = close
        self._max_size = max_size
        self._idle_ttl = idle_ttl
        self._clock = clock
        self._lock = threading.Lock()
        self._free: deque[tuple[object, float]] = deque()  # (conn, freed_at)
        self._waiters: deque[threading.Event] = deque()
        self._live = 0  # connections currently existing (held or free)

    # -- public API ---------------------------------------------------------

    def acquire(self, timeout=None):
        """Hand out a connection or raise TimeoutError after ``timeout`` seconds."""
        deadline = None if timeout is None else self._clock() + timeout
        while True:
            expired = []
            event = None
            creating = False
            conn = None
            with self._lock:
                # Serve the oldest free connection; drop idle-expired ones.
                while self._free:
                    candidate, freed_at = self._free.popleft()
                    if self._clock() - freed_at <= self._idle_ttl:
                        conn = candidate
                        break
                    expired.append(candidate)
                    self._live -= 1  # it is about to be destroyed
                if conn is None:
                    if self._live < self._max_size and not self._waiters:
                        # Only a non-waiting arrival may grow the pool, so a
                        # late arrival can never jump ahead of an older waiter.
                        self._live += 1
                        creating = True
                    else:
                        event = threading.Event()
                        self._waiters.append(event)
            for c in expired:
                self._close(c)  # no lock held
            if conn is not None:
                return conn
            if creating:
                return self._factory()  # no lock held
            # Block for a connection; no lock is held while waiting.
            if deadline is None:
                event.wait()
            else:
                remaining = deadline - self._clock()
                if remaining <= 0 or not event.wait(remaining):
                    with self._lock:
                        try:
                            self._waiters.remove(event)
                        except ValueError:
                            pass  # a release already handed us a slot
                    raise TimeoutError("timed out acquiring a connection")

    def release(self, conn):
        """Return ``conn`` to the pool, waking the oldest waiter if any."""
        event = None
        with self._lock:
            self._free.append((conn, self._clock()))
            if self._waiters:
                event = self._waiters.popleft()
        if event is not None:
            event.set()  # no lock held
