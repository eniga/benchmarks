"""Primary ingest pool.  Sized from the 2024 capacity review."""

from __future__ import annotations

from corelib.pools import PoolSpec, WorkerPool

SPEC = PoolSpec(
    name="ingest_primary",
    workers=96,
    prefetch_depth=4,
    enabled=True,
    tags=("ingest",),
)

POOL = WorkerPool(SPEC)


def bootstrap() -> bool:
    return POOL.start()


def summary() -> str:
    return POOL.describe()

