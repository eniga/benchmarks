"""Process-wide lock hierarchy.

Every lock in this process belongs to exactly one tier.  Tiers are ordered::

    registry  <  catalog  <  index  <  metrics

**Rule.** A thread may only acquire locks in strictly ascending tier order.
A thread holding ``index`` must not acquire ``catalog``; it must release
``index`` first.  This applies transitively: if a function holding a lock
calls a helper that acquires another lock, the pair must still ascend.

Reacquiring the *same* tier is permitted (all tier locks are reentrant).
Helpers whose name ends in ``_locked`` assume the caller already holds the
tier named in their docstring and take no lock of their own.
"""

from __future__ import annotations

import threading

TIERS = ("registry", "catalog", "index", "metrics")
TIER_RANK = {name: i for i, name in enumerate(TIERS)}


class _Hierarchy:
    def __init__(self) -> None:
        self.registry = threading.RLock()
        self.catalog = threading.RLock()
        self.index = threading.RLock()
        self.metrics = threading.RLock()

    def rank(self, tier: str) -> int:
        return TIER_RANK[tier]


locks = _Hierarchy()


def ascending(first: str, second: str) -> bool:
    """True if acquiring ``first`` then ``second`` respects the hierarchy."""
    return TIER_RANK[first] <= TIER_RANK[second]

