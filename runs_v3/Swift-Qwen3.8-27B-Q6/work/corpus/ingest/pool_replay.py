"""Shadow replay pool.  Disabled outside incident drills; never started in prod."""

from __future__ import annotations

from corelib.pools import PoolSpec, WorkerPool

SPEC = PoolSpec(
    name="replay_shadow",
    workers=256,
    prefetch_depth=12,
    enabled=False,
    tags=("ingest",),
)

POOL = WorkerPool(SPEC)


def bootstrap() -> bool:
    return POOL.start()


def summary() -> str:
    return POOL.describe()

