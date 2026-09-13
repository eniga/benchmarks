## L1

**(a)** The hierarchy is

```
registry  <  catalog  <  index  <  metrics
```

(rank 0..3 in `corelib/locking.py`: `TIERS = ("registry", "catalog", "index", "metrics")`).

The rule: a thread may acquire locks only in **ascending** tier order. A thread that holds a tier must not acquire a lower tier — it has to release the higher one first. The rule is transitive: if a function holding a tier calls something that acquires another tier, that pair must also ascend, which is why helper naming matters (see (b)). Re-acquiring the *same* tier is explicitly permitted, because every tier lock is a `threading.RLock` (`locks = _Hierarchy()` with one RLock per tier). So the enforced ordering is "never descend", not "strictly increase every time" — `ascending()` implements it as `<=`.

**(b)** Helpers whose name ends in `_locked` take no lock of their own: the caller must already hold the tier named in the helper's docstring. The convention is stated twice — in the `corelib/locking.py` docstring ("Helpers whose name ends in ``_locked`` assume the caller already holds the tier named in their docstring and take no lock of their own") and in module docstrings, e.g. `svc/catalog_ops.py`: "Everything here acquires the ``catalog`` tier unless the name ends in ``_locked``". Two functions that follow it:

- `svc/catalog_ops.py::_bump_generation_locked(key)` — `"""Caller must hold ``catalog``."""`; it mutates `_entries` with no `with` statement, and is called from `refresh_catalog_entry` inside `with locks.catalog:`.
- `svc/metrics_sink_02.py::_incr_locked(name, by)` — `"""Caller must hold ``metrics``."""`; called from `incr` after `with locks.metrics`.

Others in the same style: `svc/reindex_07.py::_write_shard_locked` ("Caller must hold ``index``") and the shard-class helper `_rollup_locked(self)` that every shard family defines. The inverse case is worth naming so it is not mistaken for a `_locked` helper: `svc/audit_11.py::_touch_index_stat` has a terse name but its docstring says "Acquires the ``index`` tier", and it does take `with locks.index` itself.

**(c)** Ten families, each `svc/<family>_00.py` … `svc/<family>_25.py` (26 modules each, 260 shard modules in total). Each family uses exactly one tier for all shared state, stated in its module docstring ("All shared state is guarded by the ``X`` tier"):

| family | tier | modules |
|---|---|---|
| `svc/bundle_NN.py` | catalog | 26 |
| `svc/cache_NN.py` | catalog | 26 |
| `svc/digest_NN.py` | metrics | 26 |
| `svc/dispatch_NN.py` | registry | 26 |
| `svc/ledger_NN.py` | registry | 26 |
| `svc/probe_NN.py` | metrics | 26 |
| `svc/router_NN.py` | registry | 26 |
| `svc/session_NN.py` | registry | 26 |
| `svc/stream_NN.py` | index | 26 |
| `svc/tracker_NN.py` | catalog | 26 |

That accounts for 78 catalog + 26 index + 52 metrics + 104 registry = 260 shard-class docstrings. The `svc/` modules that are **not** part of a numbered family are `svc/audit_11.py` (catalog, and it reaches into index from there), `svc/catalog_ops.py` (catalog), `svc/legacy_notes_04.py` (catalog), `svc/metrics_sink_02.py` (metrics), `svc/reindex_03.py` (index), `svc/reindex_07.py` (index).

**(d)** `False`. `ascending(first, second)` returns `TIER_RANK[first] <= TIER_RANK[second]`, i.e. `TIER_RANK["metrics"] <= TIER_RANK["catalog"]` = `3 <= 1` = `False`: acquiring `metrics` and then `catalog` is a **descent**, exactly what the hierarchy forbids. The reverse direction, `ascending("catalog", "metrics")` → `1 <= 3` → `True`, and equal tiers return `True` (`ascending("index","index")` → `True`), which is the reentrancy allowance. `ascending` is a pure predicate — it reports, it does not raise.

## L2

**(a) The violating call path**

It starts in **`svc/reindex_07.py::rebuild_shard`**, which acquires the `index` tier and then calls into `svc/catalog_ops.py`, whose `refresh_catalog_entry` acquires `catalog` — a descent from rank 2 to rank 1. The two acquisitions, in the order they happen:

```python
# svc/reindex_07.py
def rebuild_shard(shard: str, terms: list[str], payload: dict) -> int:
    """Rebuild one index shard and publish the new catalog generation."""
    with locks.index:                                  # 1st: index (rank 2)
        _write_shard_locked(shard, terms)
        generation = refresh_catalog_entry(shard, payload)   # <-- still holding index
        _shards.setdefault("__published__", []).append(shard)
    return generation
```

```python
# svc/catalog_ops.py  (the second acquisition)
def refresh_catalog_entry(key: str, payload: dict) -> int:
    """Write ``payload`` into the catalog and bump its generation.

    Acquires the ``catalog`` tier.
    """
    with locks.catalog:                                # 2nd: catalog (rank 1) - descent
```

Why it violates the rule: `locking.py` requires strictly ascending acquisitions and says the rule applies transitively when a lock holder calls a helper that acquires another lock. `refresh_catalog_entry` is not a `_locked` helper — its own docstring announces that it acquires `catalog` — so the pair (index, catalog) is a real acquisition pair and it descends. It is not merely untidy: `svc/audit_11.py::sweep` walks the legal direction (`catalog` then `index`) around the same two locks, so `rebuild_shard` and `sweep` are an A–B / B–I pair that can each hold one lock and block forever on the other. The fix is to stop nesting: hoist the catalog publish out of the `with locks.index:` block (as `svc/reindex_03.py` already does sequentially), or add a `refresh_catalog_entry_locked(key, payload)` variant and call that while holding… no — holding `index` still cannot be joined to `catalog` at all, so the correct shape is release `index`, then acquire `catalog`, i.e. do the catalog publication after the index block.

Call paths that look similar but are legal, and why:

- `svc/audit_11.py::sweep` → `_touch_index_stat`: catalog (rank 1) then index (rank 2) — ascending, and its module docstring says so ("Ascends catalog -> index, which is the permitted direction").
- `svc/reindex_03.py::rebuild_from_snapshot`: `read_catalog_snapshot()` acquires **and releases** `catalog` on the line before `with locks.index:` — sequential, never nested, so only one tier is held at a time.
- `svc/metrics_sink_02.py::incr`: `with locks.metrics:` nested inside `with locks.metrics:` — same tier, RLock, explicitly permitted ("Re-acquiring the same tier is permitted").
- `svc/legacy_notes_04.py::compact`: the descending `index → catalog` pair exists only in the historical `NOTE(2023-08)` comment; the current body acquires `catalog` alone.
- `svc/catalog_ops.py::refresh_catalog_entry` → `_bump_generation_locked`: the helper takes no lock (it is `_locked`), so no second acquisition exists.
- `svc/reindex_07.py::rebuild_shard` → `_write_shard_locked`: same reason — the `_locked` helper acquires nothing under `index`.
- `svc/tracker_NN.py::rollup` → `_rollup_locked` (and the equivalent helper in every shard family): helper-only, one tier.
- `svc/reindex_07.py::shard_terms`: acquires `index` alone; no nesting at all.

**(b) The resource ceiling that is breached**

The ceiling is `HARD_MEMORY_BUDGET`, stated in **`corelib/limits.py`**, whose docstring is the normative text: "`HARD_MEMORY_BUDGET` is the total resident buffer memory this process may commit across *all enabled* worker pools. For each enabled pool the commit is `workers * prefetch_depth * BUFFER_BYTES` and the sum over enabled pools must stay strictly under the budget. Pools constructed with `enabled=False` are never started and commit nothing." The constants are `BUFFER_BYTES = 1 << 20` (1 MiB) and `HARD_MEMORY_BUDGET = 2 << 30` (2 GiB = 2 147 483 648 bytes); `within_budget(total)` implements the strict `<`. The per-pool sizing is deliberately not in one place — `corelib/pools.py` says "Pool sizing lives with each pool's own module" — which is why the breach is only visible by combining five modules with `limits.py`.

All five ingest pools:

| module | `PoolSpec.name` | workers | prefetch_depth | enabled | commit |
|---|---|---|---|---|---|
| `ingest/pool_ingest.py` | `ingest_primary` | 96 | 4 | True | 96 × 4 × 1 MiB = 384 MiB |
| `ingest/pool_parse.py` | `parse_fanout` | 128 | 3 | True | 128 × 3 × 1 MiB = 384 MiB |
| `ingest/pool_enrich.py` | `enrich_lookup` | 64 | 8 | True | 64 × 8 × 1 MiB = 512 MiB |
| `ingest/pool_export.py` | `export_writer` | 192 | 5 | True | 192 × 5 × 1 MiB = 960 MiB |
| `ingest/pool_replay.py` | `replay_shadow` | 256 | 12 | **False** | 0 (excluded) |

Included: the four pools with `enabled=True`. Excluded: `ingest/pool_replay.py` / `replay_shadow`, because `enabled=False` and both the `limits.py` docstring ("Pools constructed with `enabled=False` are never started and commit nothing") and its own docstring ("Disabled outside incident drills; never started in prod") say it commits nothing.

Arithmetic per enabled pool (MiB, 1 MiB = `BUFFER_BYTES`):
- `ingest_primary`: 96 × 4 = 384 buffers → 384 MiB
- `parse_fanout`: 128 × 3 = 384 buffers → 384 MiB
- `enrich_lookup`: 64 × 8 = 512 buffers → 512 MiB
- `export_writer`: 192 × 5 = 960 buffers → 960 MiB

Total: 384 + 384 + 512 + 960 = **2 240 buffers → 2 240 MiB = 2 348 810 240 bytes.**

Budget: 2 GiB = 2 048 MiB = 2 147 483 648 bytes, and the rule is *strictly* under.

Breach: **2 240 MiB − 2 048 MiB = 192 MiB over the ceiling** (2 348 810 240 − 2 147 483 648 = 201 326 592 bytes). Equivalently it is at 109.4% of budget, so `within_budget(total_commit)` returns `False`; the largest compliant commit is 2 047 MiB.

Sensitivity: the single pool that dominates is `export_writer` (960 MiB — "Widened during the Q3 backfill and never narrowed"); dropping its prefetch depth from 5 to 3 frees 384 MiB (total 1 856 MiB, compliant). `enrich_lookup`'s depth 8 ("Deep prefetch because upstream latency is bursty") is the other lever: 8 → 5 frees 192 MiB, exactly the overshoot. And for scale: if an incident drill ever started `replay_shadow`, it would add 256 × 12 = 3 072 MiB, taking the total to 5 312 MiB — 2.6× the budget, which is why the enabled/disabled flag is the fact that matters here rather than the worker counts.
