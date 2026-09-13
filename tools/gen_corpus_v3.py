"""Generate the suite v3 long-context corpus.

Two needles are planted:

N1 (lock-order inversion, 2-hop across files)
    corelib/locking.py declares the hierarchy registry < catalog < index < metrics.
    Exactly one call path acquires `index` and then, via a helper defined in a
    DIFFERENT file, `catalog`. No single function body shows the inversion.

N2 (memory budget arithmetic, 5-file gather)
    corelib/limits.py states the budget rule and BUFFER_BYTES.
    Four ENABLED pools in four files exceed it; a fifth, disabled, pool is a decoy.
"""
import os, random, textwrap

random.seed(20260912)
OUT = os.path.join(os.path.dirname(__file__), "corpus_v3")

FILES = {}  # path -> source


def add(path, src):
    FILES[path] = textwrap.dedent(src).lstrip("\n")


# ---------------------------------------------------------------- contracts
add("corelib/locking.py", '''
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
''')

add("corelib/limits.py", '''
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
''')

add("corelib/pools.py", '''
    """Worker-pool plumbing.  Pool sizing lives with each pool's own module."""

    from __future__ import annotations

    import threading
    from dataclasses import dataclass, field


    @dataclass
    class PoolSpec:
        name: str
        workers: int
        prefetch_depth: int
        enabled: bool = True
        tags: tuple[str, ...] = field(default_factory=tuple)


    class WorkerPool:
        def __init__(self, spec: PoolSpec) -> None:
            self.spec = spec
            self._lock = threading.RLock()
            self._started = False

        def start(self) -> bool:
            if not self.spec.enabled:
                return False
            with self._lock:
                self._started = True
            return True

        def describe(self) -> str:
            state = "started" if self._started else "idle"
            return f"{self.spec.name}<{self.spec.workers}x{self.spec.prefetch_depth},{state}>"
''')

# ------------------------------------------------------------------ pools
POOLS = [
    ("ingest/pool_ingest.py", "ingest_primary", 96, 4, True,
     "Primary ingest pool.  Sized from the 2024 capacity review."),
    ("ingest/pool_parse.py", "parse_fanout", 128, 3, True,
     "Parse fan-out pool; one buffer per in-flight document shard."),
    ("ingest/pool_enrich.py", "enrich_lookup", 64, 8, True,
     "Enrichment pool.  Deep prefetch because upstream latency is bursty."),
    ("ingest/pool_export.py", "export_writer", 192, 5, True,
     "Export writers.  Widened during the Q3 backfill and never narrowed."),
    ("ingest/pool_replay.py", "replay_shadow", 256, 12, False,
     "Shadow replay pool.  Disabled outside incident drills; never started in prod."),
]
for path, name, workers, prefetch, enabled, blurb in POOLS:
    add(path, f'''
        """{blurb}"""

        from __future__ import annotations

        from corelib.pools import PoolSpec, WorkerPool

        SPEC = PoolSpec(
            name="{name}",
            workers={workers},
            prefetch_depth={prefetch},
            enabled={enabled},
            tags=("ingest",),
        )

        POOL = WorkerPool(SPEC)


        def bootstrap() -> bool:
            return POOL.start()


        def summary() -> str:
            return POOL.describe()
    ''')

# ----------------------------------------------------- N1: the inverted pair
add("svc/catalog_ops.py", '''
    """Catalog mutation helpers.

    Everything here acquires the ``catalog`` tier unless the name ends in
    ``_locked``, in which case the caller must already hold ``catalog``.
    """

    from __future__ import annotations

    from corelib.locking import locks

    _entries: dict[str, dict] = {}


    def _bump_generation_locked(key: str) -> int:
        """Caller must hold ``catalog``."""
        row = _entries.setdefault(key, {"generation": 0})
        row["generation"] += 1
        return row["generation"]


    def refresh_catalog_entry(key: str, payload: dict) -> int:
        """Write ``payload`` into the catalog and bump its generation.

        Acquires the ``catalog`` tier.
        """
        with locks.catalog:
            row = _entries.setdefault(key, {"generation": 0})
            row.update(payload)
            return _bump_generation_locked(key)


    def read_catalog_snapshot() -> dict[str, dict]:
        """Return a shallow copy.  Acquires ``catalog``."""
        with locks.catalog:
            return {k: dict(v) for k, v in _entries.items()}


    def catalog_size() -> int:
        with locks.catalog:
            return len(_entries)
''')

add("svc/reindex_07.py", '''
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
''')

# ------------------------------------------------------------- N1 decoys
add("svc/reindex_03.py", '''
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
''')

add("svc/audit_11.py", '''
    """Audit sweep.  Ascends catalog -> index, which is the permitted direction."""

    from __future__ import annotations

    from corelib.locking import locks

    _stats: dict[str, int] = {}


    def _touch_index_stat(name: str) -> int:
        """Acquires the ``index`` tier."""
        with locks.index:
            _stats[name] = _stats.get(name, 0) + 1
            return _stats[name]


    def sweep(names: list[str]) -> int:
        total = 0
        with locks.catalog:
            for name in names:
                total += _touch_index_stat(name)
        return total
''')

add("svc/legacy_notes_04.py", '''
    """Legacy compaction path.

    NOTE(2023-08): this used to grab ``index`` and then ``catalog``, which
    deadlocked against the reindexer.  It was rewritten to take the catalog
    tier first; the comment is kept for archaeology.
    """

    from __future__ import annotations

    from corelib.locking import locks

    _compacted: list[str] = []


    def compact(keys: list[str]) -> int:
        with locks.catalog:
            for key in keys:
                _compacted.append(key)
            return len(_compacted)
''')

add("svc/metrics_sink_02.py", '''
    """Metrics sink.  Re-enters the same tier, which the hierarchy allows."""

    from __future__ import annotations

    from corelib.locking import locks

    _counters: dict[str, int] = {}


    def _incr_locked(name: str, by: int) -> int:
        """Caller must hold ``metrics``."""
        _counters[name] = _counters.get(name, 0) + by
        return _counters[name]


    def incr(name: str, by: int = 1) -> int:
        with locks.metrics:
            with locks.metrics:  # reentrant, same tier: permitted
                return _incr_locked(name, by)
''')

# ----------------------------------------------------------- filler modules
FAMILIES = [
    ("cache", "Cache", "catalog"),
    ("router", "Router", "registry"),
    ("digest", "Digest", "metrics"),
    ("ledger", "Ledger", "registry"),
    ("probe", "Probe", "metrics"),
    ("session", "Session", "registry"),
    ("bundle", "Bundle", "catalog"),
    ("stream", "Stream", "index"),
    ("tracker", "Tracker", "catalog"),
    ("dispatch", "Dispatch", "registry"),
]
VERBS = ["put", "drop", "touch", "seal", "merge", "prune", "flush", "stamp"]

for fam, cls, tier in FAMILIES:
    for n in range(26):
        ops = []
        for k, verb in enumerate(random.sample(VERBS, 5)):
            ops.append(f'''
    def {verb}(self, key: str, value: int = {k + 1}) -> int:
        with locks.{tier}:
            self._rows[key] = self._rows.get(key, 0) + value
            return self._rows[key]
''')
        ops.append(f'''
    def _rollup_locked(self) -> int:
        """Caller must hold ``{tier}``."""
        return sum(self._rows.values())

    def rollup(self) -> int:
        with locks.{tier}:
            return self._rollup_locked()

    def snapshot(self) -> dict[str, int]:
        with locks.{tier}:
            return dict(self._rows)
''')
        body = "".join(ops)
        add(f"svc/{fam}_{n:02d}.py", f'''
            """{cls} shard {n}.  All shared state is guarded by the ``{tier}`` tier."""

            from __future__ import annotations

            from corelib.locking import locks


            class {cls}{n:02d}:
                def __init__(self) -> None:
                    self._rows: dict[str, int] = {{}}
            {body}
        ''')

os.makedirs(OUT, exist_ok=True)
order = (
    ["corelib/locking.py", "corelib/limits.py", "corelib/pools.py"]
    + [p for p, *_ in POOLS]
    + sorted(p for p in FILES if p.startswith("svc/"))
)
assert set(order) == set(FILES), set(order) ^ set(FILES)

with open(os.path.join(OUT, "corpus.txt"), "w") as fh:
    for path in order:
        fh.write(f"===== {path} =====\n")
        fh.write(FILES[path].rstrip() + "\n\n")

print("files:", len(order))
size = os.path.getsize(os.path.join(OUT, "corpus.txt"))
print("bytes:", size, "~tokens:", size // 4)
