"""Bounded, strictly FIFO connection pool (task C1).

Design notes
------------
* One non-reentrant ``threading.Lock`` guards all pool state.  It is never
  held while calling the user-supplied ``factory``/``close`` callables and
  never held while a thread blocks waiting for a connection.
* Blocking uses a per-waiter ``threading.Event`` plus an explicit FIFO
  ``deque`` of waiters.  ``Condition.wait``/``notify`` is deliberately not
  used: lock hand-off in CPython is not first-come-first-served, so with a
  condition variable a late arrival can take a connection ahead of a thread
  that has been waiting longer.
* A thread that arrives while anybody is already queued always queues behind
  them, even if a slot looks free.  That is what makes the fairness strict
  rather than best-effort.
* Idle expiry is lazy: an over-age connection is closed by the next acquire
  that inspects it.  No background thread, no timer.
* Monotonic clock only (``time.monotonic`` by default; injectable so the
  60 s expiry path is testable without sleeping for 60 s).

Accounting invariant: a connection is counted in ``self._leased`` from the
moment it is handed to a caller until it is put back on the idle shelf,
including the short window in which it is earmarked for a queued waiter.
``len(_leased) + _creating + len(_waiters_handed_off) <= max_size`` therefore
holds at all times.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Callable, Optional

DEFAULT_IDLE_TIMEOUT = 60.0


class _Waiter:
    __slots__ = ("event", "conn", "ident")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.conn: Any = None
        # Thread that is blocked on this waiter; recorded so the hand-off order
        # is observable (see ConnectionPool.last_handoffs).
        self.ident = threading.get_ident()


class ConnectionPool:
    def __init__(
        self,
        max_size: int,
        factory: Callable[[], Any],
        close: Callable[[Any], None],
        idle_timeout: float = DEFAULT_IDLE_TIMEOUT,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_size < 1:
            raise ValueError("max_size must be >= 1")
        self._max_size = int(max_size)
        self._factory = factory
        self._close = close
        self._idle_timeout = float(idle_timeout)
        self._clock = clock

        self._lock = threading.Lock()
        self._idle: list[list] = []          # [conn, released_at], oldest first
        self._leased: dict[int, Any] = {}    # id(conn) -> conn (identity-checked)
        self._creating = 0                   # slots reserved, factory in flight
        self._handed = 0                     # conns earmarked for a dequeued waiter
        self._waiters: deque[_Waiter] = deque()
        self._created = 0
        self._closed = 0
        # Bounded log of hand-off order: the thread ident of the waiter that
        # each released connection was earmarked for, oldest first.  Written
        # only under the pool lock.  Handy for debugging, and it is what makes
        # the FCFS property observable even when two slots are released at once
        # and the woken threads then log their arrival in either order.
        self.last_handoffs: deque[int] = deque(maxlen=64)

    # ----------------------- introspection (for tests) -----------------
    @property
    def max_size(self) -> int:
        return self._max_size

    @property
    def idle_timeout(self) -> float:
        return self._idle_timeout

    def counts(self) -> dict:
        with self._lock:
            return {
                "idle": len(self._idle),
                "leased": len(self._leased),
                "creating": self._creating,
                "handed": self._handed,
                "waiting": len(self._waiters),
                "created": self._created,
                "closed": self._closed,
            }

    # ------------------------------ acquire ----------------------------
    def acquire(self, timeout: Optional[float] = None) -> Any:
        deadline = None if timeout is None else self._clock() + timeout
        while True:
            handed: Any = None
            need_create = False
            waiter: Optional[_Waiter] = None
            stale: list[Any] = []

            with self._lock:
                if not self._waiters:
                    # Serve immediately only when nobody is queued ahead.
                    while self._idle:
                        rec = self._idle.pop(0)
                        if self._clock() - rec[1] > self._idle_timeout:
                            stale.append(rec[0])
                            continue
                        handed = rec[0]
                        self._leased[id(handed)] = handed
                        break
                    if handed is None and self._has_slot_locked():
                        self._creating += 1
                        need_create = True
                    elif handed is None:
                        waiter = _Waiter()
                        self._waiters.append(waiter)
                else:
                    # Strict FCFS: never take a connection ahead of a waiter.
                    waiter = _Waiter()
                    self._waiters.append(waiter)

            # -- pool lock is NOT held from here on --
            for conn in stale:                 # lazy idle expiry
                self._close_conn(conn)

            if handed is not None:
                return handed

            if need_create:
                try:
                    conn = self._factory()                 # user I/O, no lock held
                except BaseException:
                    with self._lock:
                        self._creating -= 1                # free the reserved slot
                        self._wake_head_locked()           # give it to the longest waiter
                    raise
                with self._lock:
                    self._creating -= 1
                    self._leased[id(conn)] = conn
                    self._created += 1
                return conn

            assert waiter is not None
            remaining = None if deadline is None else deadline - self._clock()
            if remaining is not None and remaining < 0:
                remaining = 0.0
            signalled = waiter.event.wait(remaining)       # blocked, no lock held

            with self._lock:
                if waiter.conn is not None:                # release() handed one over
                    conn = waiter.conn
                    waiter.conn = None
                    self._handed -= 1
                    # already counted in self._leased; ownership is now this thread
                    return conn
                try:
                    self._waiters.remove(waiter)           # we timed out / woke empty
                except ValueError:
                    pass

            if not signalled:
                raise TimeoutError(
                    f"no connection available within {timeout}s "
                    f"(max_size={self._max_size})"
                )
            if deadline is not None and self._clock() >= deadline:
                raise TimeoutError(
                    f"no connection available within {timeout}s "
                    f"(max_size={self._max_size})"
                )
            # woke with no connection (someone else won the slot): rejoin the queue

    def _has_slot_locked(self) -> bool:
        return len(self._leased) + self._creating + self._handed < self._max_size

    def _wake_head_locked(self) -> None:
        if self._waiters:
            self._waiters.popleft().event.set()

    # ------------------------------ release ----------------------------
    def release(self, conn: Any) -> None:
        wake: Optional[_Waiter] = None
        with self._lock:
            held = self._leased.get(id(conn))
            if held is not conn:
                raise RuntimeError("release(): connection is not owned by this pool")
            if self._waiters:
                head = self._waiters.popleft()             # strictly FIFO hand-off
                head.conn = conn                          # stays counted in _leased
                self._handed += 1
                self.last_handoffs.append(head.ident)
                wake = head
            else:
                self._leased.pop(id(conn), None)
                self._idle.append([conn, self._clock()])
        if wake is not None:
            wake.event.set()                               # no lock held

    def drain(self) -> int:
        """Close every idle connection (test/shutdown helper)."""
        with self._lock:
            idle, self._idle = self._idle, []
        for rec in idle:
            self._close_conn(rec[0])
        return len(idle)

    # ------------------------------- close -----------------------------
    def _close_conn(self, conn: Any) -> None:
        self._close(conn)                                  # user I/O, no lock held
        with self._lock:
            self._closed += 1
