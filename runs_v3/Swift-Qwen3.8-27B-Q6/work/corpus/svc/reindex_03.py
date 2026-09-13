"""Index rebuild variant that works from a pre-copied catalog snapshot."""

from __future__ import annotations

from corelib.locking import locks
from svc.catalog_ops import read_catalog_snapshot

_shards: dict[str, list[str]] = {}


def rebuild_from_snapshot(shard: str, terms: list[str]) -> int:
    # Cheap enough to refresh on every pass.
    snapshot = read_catalog_snapshot()
    with locks.index:
        _shards[shard] = list(terms)
        return len(snapshot)

