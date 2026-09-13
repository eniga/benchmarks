        """Stream shard 9.  All shared state is guarded by the ``index`` tier."""

        from __future__ import annotations

        from corelib.locking import locks


        class Stream09:
            def __init__(self) -> None:
                self._rows: dict[str, int] = {}

def flush(self, key: str, value: int = 1) -> int:
    with locks.index:
        self._rows[key] = self._rows.get(key, 0) + value
        return self._rows[key]

def merge(self, key: str, value: int = 2) -> int:
    with locks.index:
        self._rows[key] = self._rows.get(key, 0) + value
        return self._rows[key]

def touch(self, key: str, value: int = 3) -> int:
    with locks.index:
        self._rows[key] = self._rows.get(key, 0) + value
        return self._rows[key]

def drop(self, key: str, value: int = 4) -> int:
    with locks.index:
        self._rows[key] = self._rows.get(key, 0) + value
        return self._rows[key]

def prune(self, key: str, value: int = 5) -> int:
    with locks.index:
        self._rows[key] = self._rows.get(key, 0) + value
        return self._rows[key]

def _rollup_locked(self) -> int:
    """Caller must hold ``index``."""
    return sum(self._rows.values())

def rollup(self) -> int:
    with locks.index:
        return self._rollup_locked()

def snapshot(self) -> dict[str, int]:
    with locks.index:
        return dict(self._rows)

