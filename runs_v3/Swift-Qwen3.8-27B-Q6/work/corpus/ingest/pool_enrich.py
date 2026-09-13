"""Enrichment pool.  Deep prefetch because upstream latency is bursty."""

from __future__ import annotations

from corelib.pools import PoolSpec, WorkerPool

SPEC = PoolSpec(
    name="enrich_lookup",
    workers=64,
    prefetch_depth=8,
    enabled=True,
    tags=("ingest",),
)

POOL = WorkerPool(SPEC)


def bootstrap() -> bool:
    return POOL.start()


def summary() -> str:
    return POOL.describe()

