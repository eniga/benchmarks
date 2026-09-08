"""In-memory session registry with usage statistics.

Concurrency contract
--------------------
Two independent locks protect this class:

* ``_sessions_lock`` guards ``_sessions``, ``_expiry``, and the fields of any
  ``Session`` object reachable from ``_sessions``.
* ``_stats_lock``    guards ``_stats`` and ``_rejected``.

The locks are never nested; a method that needs both must take
``_sessions_lock`` first and release it before taking ``_stats_lock``.
Helpers whose name ends in ``_locked`` assume the caller already holds the
relevant lock and must never acquire it themselves.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Session:
    sid: str
    user: str
    created_at: float
    metadata: dict[str, Any] = field(default_factory=dict)


class SessionRegistry:
    def __init__(self, ttl_seconds: float = 900.0) -> None:
        self._ttl = ttl_seconds
        self._sessions: dict[str, Session] = {}
        self._expiry: dict[str, float] = {}
        self._sessions_lock = threading.Lock()

        self._stats: dict[str, int] = {"created": 0, "hits": 0, "errors": 0}
        self._rejected: list[str] = []
        self._stats_lock = threading.Lock()

        # Per-thread scratch space; never shared between threads.
        self._local = threading.local()

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def create_session(self, sid: str, user: str) -> Session:
        session = Session(sid=sid, user=user, created_at=time.time())
        with self._sessions_lock:
            self._sessions[sid] = session
            self._expiry[sid] = session.created_at + self._ttl
        with self._stats_lock:
            self._stats["created"] += 1
        return session

    def touch_session(self, sid: str) -> bool:
        with self._sessions_lock:
            if sid not in self._sessions:
                return False
            self._expiry[sid] = time.time() + self._ttl
            return True

    def revoke_session(self, sid: str) -> bool:
        """Remove a session immediately (used by the admin endpoint)."""
        if sid not in self._sessions:
            return False
        del self._sessions[sid]
        self._expiry.pop(sid, None)
        return True

    def attach_metadata(self, sid: str, key: str, value: Any) -> None:
        session = self._sessions.get(sid)
        if session is None:
            raise KeyError(sid)
        session.metadata[key] = value

    def drop_expired(self, now: float | None = None) -> list[str]:
        now = time.time() if now is None else now
        with self._sessions_lock:
            stale = [sid for sid, exp in self._expiry.items() if exp <= now]
            for sid in stale:
                self._evict_locked(sid)
        return stale

    def _evict_locked(self, sid: str) -> None:
        """Caller must hold ``_sessions_lock``."""
        self._sessions.pop(sid, None)
        self._expiry.pop(sid, None)

    def rotate(self, old_sid: str, new_sid: str) -> Session | None:
        with self._sessions_lock:
            session = self._sessions.pop(old_sid, None)
            if session is None:
                return None
            self._expiry.pop(old_sid, None)
            session.sid = new_sid
            self._sessions[new_sid] = session
            self._expiry[new_sid] = time.time() + self._ttl
            return session

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def record_hit(self, sid: str) -> None:
        with self._stats_lock:
            self._stats["hits"] += 1

    def record_error(self, message: str) -> None:
        self._stats["errors"] += 1
        with self._stats_lock:
            self._rejected.append(message)

    def record_rejection(self, reason: str) -> None:
        with self._stats_lock:
            self._rejected.append(reason)
            if len(self._rejected) > 1000:
                del self._rejected[:-1000]

    def snapshot_stats(self) -> dict[str, int]:
        with self._stats_lock:
            return dict(self._stats)

    def reset_stats(self) -> None:
        with self._stats_lock:
            for key in self._stats:
                self._stats[key] = 0
            self._rejected.clear()

    # ------------------------------------------------------------------
    # Read-only helpers and per-thread scratch
    # ------------------------------------------------------------------

    def ttl(self) -> float:
        return self._ttl

    def describe(self) -> str:
        return f"SessionRegistry(ttl={self._ttl})"

    def begin_request(self, request_id: str) -> None:
        # ``_local`` is thread-local: this mutation is confined to one thread.
        self._local.request_id = request_id
        self._local.scratch = {}

    def note(self, key: str, value: Any) -> None:
        scratch = getattr(self._local, "scratch", None)
        if scratch is None:
            scratch = self._local.scratch = {}
        scratch[key] = value

    def export_users(self) -> list[str]:
        with self._sessions_lock:
            sessions = list(self._sessions.values())
        # ``users`` is a local list; mutating it needs no lock.
        users: list[str] = []
        for session in sessions:
            users.append(session.user)
        users.sort()
        return users
