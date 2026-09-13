"""Index rebuild pass for the shard owned by this worker."""

from __future__ import annotations

from corelib.locking import locks
from svc.catalog_ops import refresh_catalog_entry

_shards: dict[str, list[str]] = {}


def _write_shard_locked(shard: str, terms: list[str]) -> None:
    """Caller must hold ``index``."""
    _shards[shard] = list(terms)


def rebuild_shard(shard: str, terms: list[str], payload: dict) -> int:
    """Rebuild one index shard and publish the new catalog generation."""
    with locks.index:
        _write_shard_locked(shard, terms)
        generation = refresh_catalog_entry(shard, payload)
        _shards.setdefault("__published__", []).append(shard)
    return generation


def shard_terms(shard: str) -> list[str]:
    with locks.index:
        return list(_shards.get(shard, ()))

