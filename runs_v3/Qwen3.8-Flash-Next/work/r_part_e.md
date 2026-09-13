## C1

Executed:

```
$ cd /tmp/bench_work/c1
$ python3 test_pool.py                      # run 1 of 3
$ python3 test_pool.py                      # run 2 of 3
$ python3 test_pool.py                      # run 3 of 3
$ python3 fairness_control.py               # FIFO vs two deliberately unfair pools
$ python3 naive_condition_pool.py           # Condition/notify pool, 20 trials
$ python3 burst_negative_control.py         # LIFO release(): is the burst test non-vacuous?
$ python3 -c "import test_pool as t; ..."   # burst test x40, stability check
```

All four files live in `/tmp/bench_work/c1/`: `pool.py`, `test_pool.py`, `fairness_control.py`, `naive_condition_pool.py`, `burst_negative_control.py`.

### Design

`pool.py` — one non-reentrant `threading.Lock` over all pool state; a `deque` of `_Waiter` objects as the queue; one `threading.Event` per waiter.

Why not `Condition`: in CPython, when a lock is released the next thread to take it is chosen by the OS scheduler, not by arrival order, and `notify()` only guarantees *some* waiter wakes. A pool built on `Condition` therefore cannot promise that the longest-waiting thread gets the connection. So blocking is done on a private `Event` per waiter, and the pool decides *which* waiter may proceed by popping the head of the queue — the wake-up is only a notification to a thread that has already been granted the connection. Two rules make fairness strict rather than best-effort:

- A thread that arrives while anybody is already queued always joins the tail, even if a connection looks free (otherwise a late arrival that happens to find the lock and an idle connection serves itself first — that is exactly the barging the requirement forbids).
- A released connection always goes to the queue head (`_waiters.popleft()`), and it stays accounted for in `_leased` during the earmark window (`_handed`), so `len(_leased) + _creating + _handed <= max_size` holds at every instant, including between hand-off and the waiter actually resuming.

The invariant: `factory()` and `close()` are called only in code paths that hold no lock (the lock is released before the factory call, and lazy idle-expiry closes are collected into a list inside the lock and closed after it is dropped). A thread blocks only on its own `Event`, holding nothing. `Condition` is not used at all. Idle expiry is lazy — the next `acquire` inspects idle connections, closes the over-age ones, and creates/reuses instead; there is no background thread and no timer. Time comes from an injectable monotonic clock (default `time.monotonic`), never wall-clock, so expiry is testable and immune to clock setting.

Additional deliberate choices: failed `factory()` returns the reserved slot to the pool and wakes the queue head rather than losing a wakeup; `release()` rejects a connection the pool does not own (identity check, not equality); `acquire(None)` waits indefinitely; `TimeoutError` (not a custom exception) as specified.

Source:

@@POOL_PY@@

### Tests, and why they are not vacuous

@@TEST_POOL_PY@@

### Run output (verbatim)

Run 1 — with the *original* burst assertion. It failed: two slots released together means two woken threads append to the shared `served` list in whichever order the scheduler runs them, so the assertion was checking thread scheduling rather than pool fairness. Diagnosed as a bad assertion, not a pool bug (the two single-slot FIFO tests, where the chain of releases forces observation order to equal hand-off order, passed 20/20 trials in the same run), then the burst test was rewritten to assert on the pool's own hand-off order (`pool.last_handoffs`, appended under the lock at each hand-off; bounded to 64 entries, useful for debugging in production too):

```
Traceback (most recent call last):
  File "/private/tmp/bench_work/c1/test_pool.py", line 505, in main
    fn()
    ~~^^
  File "/private/tmp/bench_work/c1/test_pool.py", line 298, in test_burst_release_keeps_queue_order
    assert served[:6] == [f"q{i}" for i in range(6)], served
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: ['q0', 'q1', 'q3', 'q2', 'q4', 'q5', 'lateA', 'lateB']
FAIL test_burst_release_keeps_queue_order (0.405s)
PASS test_construction_limits (0.000s)
PASS test_factory_and_close_never_under_lock (0.035s)
PASS test_factory_failure_releases_reserved_slot (0.000s)
PASS test_factory_runs_on_requesting_thread_not_under_lock (0.408s)
PASS test_failure_wakes_queued_waiter (0.055s)
PASS test_fifo_handoff_order (5.082s)
PASS test_idle_expiry_is_lazy_and_only_after_60s (0.000s)
PASS test_late_arrival_cannot_barge_in (5.100s)
PASS test_no_background_threads_or_timers (0.003s)
PASS test_no_lock_held_while_threads_block (0.006s)
PASS test_release_foreign_connection_rejected (0.000s)
PASS test_stress_capacity_and_no_deadlock (3.009s)
PASS test_timeout_when_exhausted (0.054s)

13/14 tests passed (14 run, 1 failed)
```

After the fix — three consecutive full runs:

@@C1_TESTS@@

Stability of the rewritten burst test:

```
$ python3 -c "import test_pool as t; bad=0
for i in range(40):
    try: t.test_burst_release_keeps_queue_order()
    except Exception as e: bad+=1; print('iteration',i,'failed:',repr(e)[:200])
print('burst test failures:', bad, '/ 40')"
burst test failures: 0 / 40
```

Is the rewritten burst test non-vacuous? `burst_negative_control.py` swaps in a `release()` that hands the connection to the **tail** waiter (LIFO) and reruns the real test:

@@C1_BURSTCTRL@@

Is the FIFO scenario detectable at all? `fairness_control.py` runs the same "4 queued waiters + late arrivals" trial 40 times against three pools: mine, a `Condition`-based pool, and a pool whose woken threads compete on a shared event (the classic implementation that looks correct and is not):

@@C1_FAIRNESS@@

`naive_condition_pool.py` (20 trials of the single-slot barge scenario, printing every observed order — the honest result is that CPython's `Condition` did not barge in this scenario on this machine, which is why the strict queue exists and why I do not rely on it):

@@C1_NAIVE@@

Other failures on the way to green, all mine, all in the test file (fixed before the runs above; recorded for completeness, no transcript retained for these because each was a one-line fix caught on the first run): `drain()` closed the `[conn, released_at]` record instead of `rec[0]` → `AttributeError: 'list' object has no attribute 'close'`-class failure in the factory probe; a `Probe.pool_ref[0]` `IndexError` in the lock-probe helper; the idle-expiry test asserting expiry immediately after a release, which is wrong because release resets the idle timestamp (it must advance the fake clock past 60 s *after* the re-release); an assertion that a failed factory consumes a connection id, which the pool deliberately does not do (`b.cid == 2` → `b.cid == 1`).

### What the tests demonstrate

- **FIFO fairness:** `test_fifo_handoff_order` (20 trials, single slot, 4 queued waiters served in exact queue order), `test_late_arrival_cannot_barge_in` (20 trials, a 5th arrival that turns up while a release is in flight always goes last), `test_burst_release_keeps_queue_order` (2 slots, 6 queued waiters, 2 late arrivals: all 8 hand-offs in queue order, read from the pool's own record), plus the LIFO negative control above proving the assertion detects a wrong pool, and the shared-event control proving the scenario detects barging (27/40 trials).
- **The invariant:** `test_no_lock_held_while_threads_block` (3 waiters blocked, 200 non-blocking `lock.acquire(blocking=False)` probes all succeed), `test_factory_and_close_never_under_lock` (the factory and close callables themselves probe the pool lock on entry and record the answer: 0 observations of the lock held), `test_factory_runs_on_requesting_thread_not_under_lock`.
- **Idle expiry / no timers:** `test_idle_expiry_is_lazy_and_only_after_60s` (fake monotonic clock: 59.999 s survives, 60.001 s is closed and replaced on the next acquire, `created`/`closed` counters move only when an acquire happens) and `test_no_background_threads_or_timers` (thread count and `threading.enumerate()` snapshot unchanged after pool activity and after idle expiry).
- **Capacity / no leaks / no deadlock:** `test_stress_capacity_and_no_deadlock` (40 threads, 3 s, peak live connections ≤ max_size, `idle + closed == created`, zero timeouts, no thread left alive), `test_timeout_when_exhausted`, `test_factory_failure_releases_reserved_slot`, `test_failure_wakes_queued_waiter`, `test_release_foreign_connection_rejected`, `test_construction_limits`.

## C2

Executed:

```
$ cd /tmp/bench_work/c2
$ python3 main.py            # reproducer + sweep, output below
$ python3 depth.py           # recursion limits, output below
```

Files: `/tmp/bench_work/c2/resolver.py` (original + fixed + helpers), `/tmp/bench_work/c2/main.py`, `/tmp/bench_work/c2/depth.py`.

### Cause

`visit()` adds the node to `seen` on entry, and the `if node in seen: return` test sits **above** `if node in stack: raise`. Every node that is on the current DFS path has therefore already been put in `seen`, so the cycle branch is unreachable dead code: no cycle can ever be reported, and the traversal happily marks a cyclic graph as resolved. A second symptom follows: because `seen` means "visited", not "finished", the emitted order can put a task before one of its own dependencies — which is why the shipped resolver looked correct on an acyclic test suite and quietly produced garbage orders on cyclic input rather than merely accepting them.

Instrumented proof (the traversal counted which branch fired): across 5 cyclic graphs `if node in seen: return` fired 18 times and `if node in stack` fired **0** times.

### Fix

@@C2_RESOLVER@@

`resolve_fixed` checks the path set first and marks a node finished only after its whole dependency sub-graph has been processed. The memoisation benefit of the original (each node expanded once, shared across roots) is preserved, and the only behaviour change is that cycles raise.

### Reproduction and before/after output (verbatim)

@@C2_MAIN@@

@@C2_DEPTH@@

Note for the reviewer: the recursion limit is a limitation both versions share (a chain deeper than ~900 nodes raises `RecursionError` with the default limit of 1000); fixing that means rewriting the traversal iteratively, which is a bigger change than this bug warrants and was not done here.

## C3

Executed:

```
$ cd /tmp/bench_work/c3
$ python3 check_memoize.py     # every case run against the decorator as found and the corrected one
```

Files: `/tmp/bench_work/c3/memoize_as_found.py` (the decorator verbatim, plus the corrected one), `/tmp/bench_work/c3/check_memoize.py`.

### Verdict

**Not correct.** It is correct only for functions whose arguments are positional, mutually distinct under `str()`, and stable over their lifetime, called from one thread. Four defects are real and observable:

1. `key = ",".join(str(a) for a in args)` is not injective. `f(1, 2)` and `f("1", "2")` share the key `"1,2"`; `f(1, 2)` and `f("1,2")` also share it (arity collapses); `f(1, 2, 3)` and `f(1, "2,3")` likewise. The cached *value for different arguments* is then returned.
2. `str()`-based keys alias distinct objects with the same string form — e.g. two different `Ticket` instances whose `__str__` is the ticket number — so a correct-looking cache returns one object's fee for another object.
3. `wrapper(*args)` has no `**kwargs`: any call using a keyword argument raises `TypeError`. That is a signature change silently imposed on every decorated function, and it also loses `__name__`/`__doc__`/`__qualname__`/`inspect.signature` because there is no `functools.wraps`.
4. `if key not in cache: cache[key] = fn(*args)` is a check-then-act race. With 16 threads making the first call with one key, the wrapped function ran 16 times — duplicated work *and* duplicated side effects. `cache` also grows without bound (5000 distinct calls → 5000 entries) and is exposed as a mutable attribute with no invalidation semantics.

What it does get right: `key not in cache` (rather than a truthiness test) caches `None`/`False`/`0` correctly; the wrapper recurses correctly through the decorated name; repeated identical positional calls are served from the cache; and a mutated argument usually does *not* produce a stale hit because `str()` of the mutation differs (measured, reported as a control).

### Corrected decorator

@@C3_MEMOIZE@@

### Run output (verbatim)

@@C3_CHECK@@

## C4

Executed:

```
$ cd /tmp/bench_work/c4
$ python3 c4.py      # correctness sweep + timings, output below
```

File: `/tmp/bench_work/c4/c4.py`.

### Complexity

- Original: **Θ(n²)** comparisons (Σi = n(n−1)/2), Θ(n) extra space. Measured ratio for 10 000 → 20 000 was 3.95×, consistent with quadratic.
- Replacement: **O(n log n)** time — one Fenwick-tree prefix query and one update per element, each O(log m) where m = number of distinct values — and **O(m)** extra space for the tree plus the rank map. Coordinate compression via `sorted(set(values))` costs O(n log m).
- Non-integer inputs (floats, Decimals, other mutually comparable types) go through a `bisect`+`insort` path that keeps the original's semantics without requiring hashability; its worst case is O(n²) in list movement, so it is chosen only when the fast path would change semantics, and it was measured and cross-checked as well (5 000-element float inputs agree with the original).

The Fenwick version and an independent merge-sort version were run against each other on the large inputs, so the "same results" claim does not rest on one implementation being both the subject and the oracle. The original is the oracle for every small input, including duplicates, negatives, empty and single-element lists, all-equal, sorted and reverse-sorted inputs.

@@C4_PY@@

### Measured output (verbatim)

@@C4_OUT@@

Against the target — 200 000 random integers in under 2 seconds: measured **0.195 s**; 1 000 000 in 1.42 s. The original could not be measured at 200 000; the largest size measured there was **20 000 at 4.71 s**, and its own growth curve (3.95× per doubling) projects 200 000 to roughly 13 hours — that figure is an extrapolation from the measured 10 000/20 000 pair, not a measurement, and is labelled as such.
