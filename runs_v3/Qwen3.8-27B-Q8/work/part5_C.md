## C1
Executed: `cd work/c1 && python3 test_pool.py` and `cd work/c1 && python3 stress_pool.py`

```
PASS test_fifo_fairness: served order ['B', 'C', 'D']
PASS test_late_arrival_cannot_jump_queue: served order ['B', 'C', 'D-late']
PASS test_no_lock_held_during_factory_and_close
PASS test_no_lock_held_while_blocked_waiting
PASS test_acquire_timeout
PASS test_idle_eviction_lazy
PASS test_reuse_and_bounds
ALL C1 TESTS PASSED
```
```
STRESS OK: 16 workers x 300 ops in 0.58s, created=4, closed=0, live=4
```

**Implementation** (`pool.py`):

```python
import threading
import time
from collections import deque


class _Waiter:
    __slots__ = ("event", "conn", "name")
    def __init__(self, name=None):
        self.event = threading.Event()
        self.conn = None
        self.name = name


class ConnectionPool:
    def __init__(self, factory, close, max_size, idle_ttl=60.0):
        if max_size < 1:
            raise ValueError("max_size must be >= 1")
        self._factory = factory
        self._close = close
        self._max_size = max_size
        self._idle_ttl = idle_ttl
        self._lock = threading.Lock()
        self._idle = deque()      # deque of (conn, returned_at_monotonic)
        self._live = 0            # idle + checked out
        self._waiters = deque()   # FIFO of _Waiter

    def _pop_idle_locked(self):
        """Pop a fresh idle conn, collecting stale ones to close (caller closes
        them outside the lock). Returns (conn_or_None, stale_list)."""
        now = time.monotonic()
        stale = []
        while self._idle:
            conn, since = self._idle.popleft()
            if now - since <= self._idle_ttl:
                return conn, stale
            stale.append(conn)
            self._live -= 1
        return None, stale

    def _wake_head_locked(self):
        if self._waiters:
            self._waiters.popleft().event.set()

    def acquire(self, timeout=None, _waiter_name=None):
        deadline = None
        if timeout is not None:
            deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                conn, stale = self._pop_idle_locked()
                if conn is None:
                    # Grow only if nobody is waiting, so a late arrival can never
                    # take a connection ahead of a longer waiter.
                    if not self._waiters and self._live < self._max_size:
                        self._live += 1
                        creating, waiter = True, None
                    else:
                        creating = False
                        waiter = _Waiter(name=_waiter_name)
                        self._waiters.append(waiter)
            for c in stale:            # close evicted conns OUTSIDE the lock
                self._close(c)
            if conn is not None:
                return conn
            if creating:               # factory OUTSIDE the lock
                try:
                    return self._factory()
                except BaseException:
                    with self._lock:
                        self._live -= 1
                        self._wake_head_locked()
                    raise
            # block on a per-waiter Event; the pool lock is NOT held here
            if deadline is None:
                waiter.event.wait()
            else:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    with self._lock:
                        self._remove_waiter(waiter)
                    raise TimeoutError("timed out acquiring a connection")
                if not waiter.event.wait(remaining):
                    with self._lock:
                        handed = waiter.conn
                        if handed is None:
                            self._remove_waiter(waiter)
                    if handed is not None:
                        return handed
                    raise TimeoutError("timed out acquiring a connection")
            if waiter.conn is not None:
                return waiter.conn
            # woken without a conn (slot freed by a failed creation): loop

    def release(self, conn):
        with self._lock:
            if self._waiters:
                waiter = self._waiters.popleft()
                waiter.conn = conn
                waiter.event.set()     # non-blocking; safe under the lock
            else:
                self._idle.append((conn, time.monotonic()))

    def _remove_waiter(self, waiter):
        try:
            self._waiters.remove(waiter)
        except ValueError:
            pass

    def waiter_count(self):
        with self._lock:
            return len(self._waiters)

    def live_count(self):
        with self._lock:
            return self._live
```

**How the requirements map to the design**
- *Fixed max size*: `max_size` at construction; `_live` never exceeds it (a slot is reserved under the lock before the factory runs, and released on failure).
- *FIFO fairness*: waiters are appended to `_waiters` in arrival order; `release()` always hands the connection to `_waiters.popleft()` (the longest waiter). A thread may only *create* (grow the pool) when `_waiters` is empty, so a late arrival can never grab a connection ahead of a longer waiter.
- *Idle > 60 s closed lazily*: `_pop_idle_locked` evicts entries older than `idle_ttl` (default 60) on the next `acquire`; no background threads/timers; `time.monotonic()` only.
- *Invariant*: `factory` and `close` are called only after the `with self._lock` block has exited; waiting is on a per-waiter `threading.Event`, which does not hold the pool lock.

**How the tests demonstrate the two required properties**
- `test_fifo_fairness` and `test_late_arrival_cannot_jump_queue`: three threads are parked in the waiter queue (order pinned to B, C, D by gating each start on `waiter_count`), the single connection is released once, and the test asserts the *served* order is exactly B, C, D (and that a late arrival is served last). This is the FIFO property, not a happy-path check.
- `test_no_lock_held_during_factory_and_close`: the factory/close callables assert the pool lock is *free* by attempting a non-blocking `acquire(blocking=False)`; if the pool ever held the lock across a factory/close call, the assertion fires.
- `test_no_lock_held_while_blocked_waiting`: a thread is observably parked in the queue, and the main thread then acquires the pool lock — which would deadlock if the blocked waiter held it.
- `stress_pool.py`: 16 workers × 300 ops on a 4-connection pool with a short idle TTL; asserts no deadlock, no invariant violation, and no leak (`created - closed == live`).

## C2
Executed: `cd work/c2 && python3 repro.py` (original) and `cd work/c2 && python3 fixed.py` (fixed)

**Reproducer input** (a cyclic graph that must be rejected): `{"a": ["b"], "b": ["a"]}`, plus a self-loop, a 3-cycle, and a 2-cycle with a tail.

**Output before the fix** (`repro.py`):
```
Cyclic graphs (should all be REJECTED with ValueError):
  self-loop a->a: BUG -- accepted a cyclic graph, returned ['a']
  2-cycle a<->b: BUG -- accepted a cyclic graph, returned ['b', 'a']
  3-cycle a->b->c->a: BUG -- accepted a cyclic graph, returned ['c', 'b', 'a']
  2-cycle y<->z with tail x: BUG -- accepted a cyclic graph, returned ['z', 'y', 'x']
  => 0/4 cycles correctly rejected (4 wrongly ACCEPTED)

Acyclic graphs (should all be ACCEPTED, valid order):
  diamond DAG: returned ['db', 'lib', 'app']  (valid topo order: True)
  shared dependency: returned ['d', 'b', 'c', 'a']  (valid topo order: True)
  single node: returned ['solo']  (valid topo order: True)
  => 3/3 DAGs correctly accepted
```

**Diagnosis.** The cycle check is dead code. `seen` is a *global visited* set that a node is added to the instant it is first entered:
```python
stack.add(node)
seen.add(node)      # marked "seen" before its deps are even explored
```
and the checks run in this order:
```python
if node in seen:    # <-- fires FIRST for a back edge
    return
if node in stack:   # <-- unreachable for back edges
    raise ValueError(...)
```
Every node on the current DFS path is in `stack` *and*, simultaneously, in `seen` (they are added together). So a back edge — the thing that actually identifies a cycle — always hits `node in seen` and returns early; the `node in stack` raise is never reached. Result: **no cycle is ever detected**, and any cyclic project is accepted with a bogus "build order." That is exactly the user's report.

**Fix** (standard three-colour DFS; a node is marked done only after it and all its dependencies are fully ordered, so the current path in `stack` is the only thing that reaches the raise):
```python
def resolve(graph):
    order = []
    seen = set()  # "black": fully processed (node and all its deps done)

    def visit(node, stack):
        if node in seen:
            return                       # cross/forward edge: already ordered
        if node in stack:
            raise ValueError(f"cycle through {node}")  # back edge: a cycle
        stack.add(node)                  # "gray": on the current path
        for dep in graph.get(node, ()):
            visit(dep, stack)
        stack.discard(node)
        seen.add(node)                   # mark done only after all deps ordered
        order.append(node)

    for node in graph:
        visit(node, set())
    return order
```

**Output after the fix** (`fixed.py`):
```
ok: rejected cyclic ['a']
  ok: rejected cyclic ['a', 'b']
  ok: rejected cyclic ['a', 'b', 'c']
  ok: rejected cyclic ['x', 'y', 'z']
  ok: DAG ['app', 'db', 'lib'] -> ['db', 'lib', 'app']
  ok: DAG ['a', 'b', 'c', 'd'] -> ['d', 'b', 'c', 'a']
  ok: DAG ['solo'] -> ['solo']
  ok: DAG [] -> []
  differential: 5000 random graphs (2865 cyclic), 0 mismatches

ALL C2 CHECKS PASSED
```
All four cyclic inputs now raise `ValueError`; all DAGs still produce valid topological orders; and a 5000-graph differential test (2865 of them cyclic) agrees exactly with an independent Kahn's-algorithm reference (0 mismatches).

## C3
Executed: `cd work/c3 && python3 memoize_check.py`

```
f("a,b","c") = ['a,b', 'c']
f("a","b,c") = ['a,b', 'c']   (correct value would be ["a", "b,c"])
  -> key collision returned a wrong value: True

g(1,"2,3")   = (1, '2,3')
g("1","2,3") = (1, '2,3')   (correct value would be ("1", "2,3"))
  -> int/str collision returned a wrong value: True

  calling with keyword args raised TypeError: memoize.<locals>.wrapper() got an unexpected keyword argument 'a'

  repeated identical call computed once: True

C3 DEMONSTRATION COMPLETE (decorator is INCORRECT)
```

**Verdict: not correct.** The cache key is not a well-defined (injective) function of the arguments, so the wrapper can return a value computed for a *different* input.

The key is `",".join(str(a) for a in args)`. Stringifying and comma-joining is not injective:
- `f("a,b", "c")` → key `"a,b,c"`; `f("a", "b,c")` → key `"a,b,c"`. Different argument tuples, identical key, so the second call returns the first call's cached value `["a,b", "c"]` instead of `["a", "b,c"]`.
- The same collision happens across types: `g(1, "2,3")` and `g("1", "2,3")` both key to `"1,2,3"`.

A secondary defect: `wrapper(*args)` accepts only positional arguments, so calling the wrapped function with keyword arguments raises `TypeError` (demonstrated above).

What it *does* do correctly: for a fixed, unambiguous positional-args tuple it is consistent and computes the value once (the "repeated identical call computed once: True" line). But correctness requires returning the right value for *every* input, and the key collision breaks that, so the decorator is incorrect. The fix is to key on the actual argument tuple (e.g. `args` itself, or a canonical serialization that is injective such as `repr(args)` with care for non-repr-stable types, or hashing the tuple), and to handle `*args, **kwargs` if keyword calls must be supported.

## C4
Executed: `cd work/c4 && python3 optimize.py`

```
equivalence: original == optimized on all randomized + structured inputs (incl. negatives and duplicates)

timing (original, O(n^2)):
  original n=  1000:    0.011s
  original n=  2000:    0.047s
  original n=  4000:    0.195s
  original n=  8000:    0.799s
  original n= 16000:    3.316s
  original n= 20000:    5.071s

timing (optimized, O(n log n)):
  optimized n=200000:    0.251s  (best of 3, under 2s: True)

C4 COMPLETE: equivalent and fast
```

**Optimized implementation** (Fenwick tree / Binary Indexed Tree over coordinate-compressed values):
```python
def count_smaller_before_fast(nums):
    n = len(nums)
    if n == 0:
        return []
    sorted_unique = sorted(set(nums))                 # handles negatives + dups
    rank = {v: i + 1 for i, v in enumerate(sorted_unique)}
    m = len(sorted_unique)
    tree = [0] * (m + 1)

    def update(i):
        while i <= m:
            tree[i] += 1
            i += i & (-i)

    def query(i):
        s = 0
        while i > 0:
            s += tree[i]
            i -= i & (-i)
        return s

    out = [0] * n
    for idx, v in enumerate(nums):
        r = rank[v]
        out[idx] = query(r - 1)   # strictly smaller == rank strictly less
        update(r)
    return out
```

**Why it is identical.** Scanning left to right, `query(r-1)` counts how many previously-seen values have rank strictly less than `r`, i.e. value strictly less than `v` — exactly the original's inner count. Coordinate compression preserves strict order for any orderable values (including negatives) and maps equal values to the same rank, so duplicates are counted correctly (an equal value has the same rank, not a smaller one, and is therefore not counted).

**Equivalence.** The test compared original vs optimized on 400 random lists (sizes 0–60, small value ranges to force heavy duplicates, negative and positive) plus structured cases (strictly increasing, strictly decreasing, all-equal, 2000 random in ±1000, 3000 drawn from {1,2,3}) — all matched. A 2000-element prefix of the 200k input was also spot-checked against the original.

**Complexity.** Original: O(n²) time, O(n) space. Optimized: O(n log n) time (one query + one update per element, each O(log m)), O(n) space.

**Timings.** The original was too slow to measure at 200,000 (at n=20,000 it already took 5.07 s; extrapolating the quadratic gives ~8 minutes at 200,000), so I reported the largest sizes I did measure (up to n=20,000). The optimized version processed 200,000 random integers in **0.251 s** (best of 3), well under the 2 s target.
