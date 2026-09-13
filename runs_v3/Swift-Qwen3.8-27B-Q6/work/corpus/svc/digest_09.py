        """Digest shard 9.  All shared state is guarded by the ``metrics`` tier."""

        from __future__ import annotations

        from corelib.locking import locks


        class Digest09:
            def __init__(self) -> None:
                self._rows: dict[str, int] = {}

def prune(self, key: str, value: int = 1) -> int:
    with locks.metrics:
        self._rows[key] = self._rows.get(key, 0) + value
        return self._rows[key]

def drop(self, key: str, value: int = 2) -> int:
    with locks.metrics:
        self._rows[key] = self._rows.get(key, 0) + value
        return self._rows[key]

def touch(self, key: str, value: int = 3) -> int:
    with locks.metrics:
        self._rows[key] = self._rows.get(key, 0) + value
        return self._rows[key]

def seal(self, key: str, value: int = 4) -> int:
    with locks.metrics:
        self._rows[key] = self._rows.get(key, 0) + value
        return self._rows[key]

def put(self, key: str, value: int = 5) -> int:
    with locks.metrics:
        self._rows[key] = self._rows.get(key, 0) + value
        return self._rows[key]

def _rollup_locked(self) -> int:
    """Caller must hold ``metrics``."""
    return sum(self._rows.values())

def rollup(self) -> int:
    with locks.metrics:
        return self._rollup_locked()

def snapshot(self) -> dict[str, int]:
    with locks.metrics:
        return dict(self._rows)

