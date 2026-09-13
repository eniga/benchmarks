## L1
**(a) Lock tier ordering and the acquisition rule.**

The required ordering, lowest to highest, is:

    registry  <  catalog  <  index  <  metrics

The governing rule (from `corelib/locking.py`): a thread may only acquire locks in **strictly ascending** tier order. A thread holding a higher-tier lock must not acquire a lower-tier lock — it must release the higher one first (e.g. holding `index` and then acquiring `catalog` is forbidden). This applies **transitively**: if a function that holds a lock calls a helper that acquires another lock, the pair must still ascend. Reacquiring the **same** tier is permitted, because every tier lock is a reentrant `RLock`.

**(b) Naming convention for lock-free helpers, with two examples.**

A helper whose name ends in **`_locked`** assumes the caller already holds the tier named in its docstring and takes no lock of its own. Two functions in the corpus that follow it:
- `svc/catalog_ops.py::_bump_generation_locked` — docstring "Caller must hold ``catalog``."
- `svc/reindex_07.py::_write_shard_locked` — docstring "Caller must hold ``index``."

(Other valid examples: `svc/metrics_sink_02.py::_incr_locked`, and every shard class's `_rollup_locked`.)

**(c) Families of numbered shard modules and the single lock tier each uses.**

All families run `_00` through `_25` (26 shards each):

| Family | Files | Lock tier |
|--------|-------|-----------|
| `bundle` | `svc/bundle_00.py` … `svc/bundle_25.py` | catalog |
| `cache`  | `svc/cache_00.py` … `svc/cache_25.py`  | catalog |
| `digest` | `svc/digest_00.py` … `svc/digest_25.py` | metrics |
| `dispatch` | `svc/dispatch_00.py` … `svc/dispatch_25.py` | registry |
| `ledger` | `svc/ledger_00.py` … `svc/ledger_25.py` | registry |
| `probe`  | `svc/probe_00.py` … `svc/probe_25.py`  | metrics |
| `router` | `svc/router_00.py` … `svc/router_25.py` | registry |
| `session`| `svc/session_00.py` … `svc/session_25.py` | registry |
| `stream` | `svc/stream_00.py` … `svc/stream_25.py` | index |
| `tracker`| `svc/tracker_00.py` … `svc/tracker_25.py` | catalog |

Ten families in total. (The numbered files `svc/audit_11.py`, `svc/legacy_notes_04.py`, `svc/metrics_sink_02.py`, `svc/reindex_03.py` and `svc/reindex_07.py` are single/paired utility modules, not numbered shard families.)

**(d) What `ascending("metrics", "catalog")` returns, and why.**

It returns **`False`**. `ascending(first, second)` is defined as `TIER_RANK[first] <= TIER_RANK[second]`, with `TIER_RANK = {registry: 0, catalog: 1, index: 2, metrics: 3}`. So `ascending("metrics", "catalog")` evaluates `3 <= 1`, which is `False`. Acquiring `metrics` (the highest tier) and then `catalog` (a lower tier) would be a *descent*, which violates the strictly-ascending rule, so the helper correctly reports it as not permitted.

## L2
**(a) The single lock-ordering violation.**

The violating path starts in **`svc/reindex_07.py`**, function **`rebuild_shard`**. The two acquisitions, in the order they happen:

1. `with locks.index:` — in `rebuild_shard` (`svc/reindex_07.py`). Acquires the **index** tier (rank 2) and holds it.
2. `with locks.catalog:` — in `refresh_catalog_entry` (`svc/catalog_ops.py`), which `rebuild_shard` calls *while still inside the `with locks.index` block* (`generation = refresh_catalog_entry(shard, payload)`). Acquires the **catalog** tier (rank 1).

Why it violates the rule: the thread holds the **index** tier and then acquires the **catalog** tier, which is a *descent* (rank 2 → rank 1). The hierarchy requires strictly ascending acquisition, so holding `index` and then taking `catalog` is forbidden. It is precisely the pattern `svc/legacy_notes_04.py` documents as having deadlocked against the reindexer ("this used to grab ``index`` and then ``catalog``, which deadlocked against the reindexer").

Similar-looking paths I considered and **rejected** as legal:
- `svc/reindex_03.py::rebuild_from_snapshot` — calls `read_catalog_snapshot()` (which acquires `catalog`) and then acquires `locks.index`. Legal: the `catalog` lock is fully released inside `read_catalog_snapshot()` before the `index` lock is taken (never held simultaneously), and the catalog→index sequence is ascending anyway.
- `svc/audit_11.py::sweep` — acquires `locks.catalog`, then calls `_touch_index_stat` which acquires `locks.index`. Legal: catalog (rank 1) → index (rank 2) is ascending.
- `svc/legacy_notes_04.py::compact` — now acquires only `locks.catalog` (the old index-then-catalog order was removed in the 2023-08 rewrite). Legal.
- `svc/metrics_sink_02.py::incr` — acquires `locks.metrics` twice (nested). Legal: same-tier reacquisition is permitted because the tier locks are reentrant.

**(b) The resource-ceiling breach.**

**Ceiling and where it is stated:** `corelib/limits.py` defines `HARD_MEMORY_BUDGET = 2 << 30` (2 GiB) as "the total resident buffer memory this process may commit across *all enabled* worker pools," with per-pool commit `workers * prefetch_depth * BUFFER_BYTES` (`BUFFER_BYTES = 1 << 20`, 1 MiB) and the sum required to stay **strictly under** the budget. Pools constructed with `enabled=False` "are never started and commit nothing."

**Every pool** (from the `ingest/` modules):

| Pool | workers | prefetch_depth | enabled | Included? |
|------|---------|----------------|---------|-----------|
| `ingest_primary` | 96  | 4  | True  | yes |
| `parse_fanout`   | 128 | 3  | True  | yes |
| `enrich_lookup`  | 64  | 8  | True  | yes |
| `export_writer`  | 192 | 5  | True  | yes |
| `replay_shadow`  | 256 | 12 | False | **no** — `enabled=False`, never started, commits nothing |

**Arithmetic** (1 MiB = 1,048,576 B):
- `ingest_primary`: 96 × 4 × 1 MiB = **384 MiB** (402,653,184 B)
- `parse_fanout`: 128 × 3 × 1 MiB = **384 MiB** (402,653,184 B)
- `enrich_lookup`: 64 × 8 × 1 MiB = **512 MiB** (536,870,912 B)
- `export_writer`: 192 × 5 × 1 MiB = **960 MiB** (1,006,632,960 B)
- **Total enabled commit = 384 + 384 + 512 + 960 = 2240 MiB (2,348,810,240 B)**

**Budget** = 2 GiB = **2048 MiB (2,147,483,648 B)**.

**Breach = 2240 − 2048 = 192 MiB (201,326,592 B).** `within_budget(2,348,810,240)` returns `False` (2,348,810,240 < 2,147,483,648 is false), so the enabled pools, taken together, exceed the stated 2 GiB ceiling by 192 MiB.
