"""Export writers.  Widened during the Q3 backfill and never narrowed."""

from __future__ import annotations

from corelib.pools import PoolSpec, WorkerPool

SPEC = PoolSpec(
    name="export_writer",
    workers=192,
    prefetch_depth=5,
    enabled=True,
    tags=("ingest",),
)

POOL = WorkerPool(SPEC)


def bootstrap() -> bool:
    return POOL.start()


def summary() -> str:
    return POOL.describe()

