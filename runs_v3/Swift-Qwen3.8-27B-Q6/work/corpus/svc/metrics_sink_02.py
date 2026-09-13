"""Metrics sink.  Re-enters the same tier, which the hierarchy allows."""

from __future__ import annotations

from corelib.locking import locks

_counters: dict[str, int] = {}


def _incr_locked(name: str, by: int) -> int:
    """Caller must hold ``metrics``."""
    _counters[name] = _counters.get(name, 0) + by
    return _counters[name]


def incr(name: str, by: int = 1) -> int:
    with locks.metrics:
        with locks.metrics:  # reentrant, same tier: permitted
            return _incr_locked(name, by)

