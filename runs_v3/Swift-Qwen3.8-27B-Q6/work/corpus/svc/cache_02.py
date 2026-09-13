        """Cache shard 2.  All shared state is guarded by the ``catalog`` tier."""

        from __future__ import annotations

        from corelib.locking import locks


        class Cache02:
            def __init__(self) -> None:
                self._rows: dict[str, int] = {}

def drop(self, key: str, value: int = 1) -> int:
    with locks.catalog:
        self._rows[key] = self._rows.get(key, 0) + value
        return self._rows[key]

def stamp(self, key: str, value: int = 2) -> int:
    with locks.catalog:
        self._rows[key] = self._rows.get(key, 0) + value
        return self._rows[key]

def prune(self, key: str, value: int = 3) -> int:
    with locks.catalog:
        self._rows[key] = self._rows.get(key, 0) + value
        return self._rows[key]

def put(self, key: str, value: int = 4) -> int:
    with locks.catalog:
        self._rows[key] = self._rows.get(key, 0) + value
        return self._rows[key]

def seal(self, key: str, value: int = 5) -> int:
    with locks.catalog:
        self._rows[key] = self._rows.get(key, 0) + value
        return self._rows[key]

def _rollup_locked(self) -> int:
    """Caller must hold ``catalog``."""
    return sum(self._rows.values())

def rollup(self) -> int:
    with locks.catalog:
        return self._rollup_locked()

def snapshot(self) -> dict[str, int]:
    with locks.catalog:
        return dict(self._rows)

