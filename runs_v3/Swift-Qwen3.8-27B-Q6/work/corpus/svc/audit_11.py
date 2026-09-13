"""Audit sweep.  Ascends catalog -> index, which is the permitted direction."""

from __future__ import annotations

from corelib.locking import locks

_stats: dict[str, int] = {}


def _touch_index_stat(name: str) -> int:
    """Acquires the ``index`` tier."""
    with locks.index:
        _stats[name] = _stats.get(name, 0) + 1
        return _stats[name]


def sweep(names: list[str]) -> int:
    total = 0
    with locks.catalog:
        for name in names:
            total += _touch_index_stat(name)
    return total

