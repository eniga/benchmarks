"""Resource ceilings for the ingest fleet.

``HARD_MEMORY_BUDGET`` is the total resident buffer memory this process may
commit across *all enabled* worker pools.  For each enabled pool the commit
is::

    workers * prefetch_depth * BUFFER_BYTES

and the sum over enabled pools must stay strictly under the budget.  Pools
constructed with ``enabled=False`` are never started and commit nothing.
"""

from __future__ import annotations

BUFFER_BYTES = 1 << 20          # 1 MiB per in-flight buffer
HARD_MEMORY_BUDGET = 2 << 30    # 2 GiB


def pool_commit(workers: int, prefetch_depth: int) -> int:
    return workers * prefetch_depth * BUFFER_BYTES


def within_budget(total_commit: int) -> bool:
    return total_commit < HARD_MEMORY_BUDGET

