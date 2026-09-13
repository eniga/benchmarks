"""Catalog mutation helpers.

Everything here acquires the ``catalog`` tier unless the name ends in
``_locked``, in which case the caller must already hold ``catalog``.
"""

from __future__ import annotations

from corelib.locking import locks

_entries: dict[str, dict] = {}


def _bump_generation_locked(key: str) -> int:
    """Caller must hold ``catalog``."""
    row = _entries.setdefault(key, {"generation": 0})
    row["generation"] += 1
    return row["generation"]


def refresh_catalog_entry(key: str, payload: dict) -> int:
    """Write ``payload`` into the catalog and bump its generation.

    Acquires the ``catalog`` tier.
    """
    with locks.catalog:
        row = _entries.setdefault(key, {"generation": 0})
        row.update(payload)
        return _bump_generation_locked(key)


def read_catalog_snapshot() -> dict[str, dict]:
    """Return a shallow copy.  Acquires ``catalog``."""
    with locks.catalog:
        return {k: dict(v) for k, v in _entries.items()}


def catalog_size() -> int:
    with locks.catalog:
        return len(_entries)

