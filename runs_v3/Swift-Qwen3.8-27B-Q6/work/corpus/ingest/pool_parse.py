"""Parse fan-out pool; one buffer per in-flight document shard."""

from __future__ import annotations

from corelib.pools import PoolSpec, WorkerPool

SPEC = PoolSpec(
    name="parse_fanout",
    workers=128,
    prefetch_depth=3,
    enabled=True,
    tags=("ingest",),
)

POOL = WorkerPool(SPEC)


def bootstrap() -> bool:
    return POOL.start()


def summary() -> str:
    return POOL.describe()

