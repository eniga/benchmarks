"""Task C4 - count_smaller_before: original vs replacement, plus measurements."""

from __future__ import annotations

import bisect
import random
import time


# --------------------------------------------------------------------------
# as found
# --------------------------------------------------------------------------
def count_smaller_before(values):
    """For each i, how many j < i have values[j] < values[i]."""
    out = []
    for i, v in enumerate(values):
        n = 0
        for j in range(i):
            if values[j] < v:
                n += 1
        out.append(n)
    return out


# --------------------------------------------------------------------------
# replacement: Fenwick tree (binary indexed tree) over the sorted distinct values
# --------------------------------------------------------------------------
def count_smaller_before_fast(values):
    """Same result as count_smaller_before, O(n log n).

    For each position we need the number of previously seen values that are
    strictly smaller.  Coordinate-compress the distinct values to 1..m, keep a
    Fenwick tree of "how many of each rank have been seen", query the prefix
    [1, rank(v)-1], then add one for v.  Duplicates and negative numbers need
    no special casing: equal values share a rank and are therefore never
    counted, which is exactly what "strictly smaller" means.
    """
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [0]

    # Fast path: plain ints (the stated input). Anything else uses the
    # comparison-based path below, so behaviour stays identical for floats,
    # Decimals, or mixed comparable types.
    for v in values:
        if type(v) is not int:
            return _count_smaller_insort(values)

    order = sorted(set(values))
    rank = {v: i + 1 for i, v in enumerate(order)}       # 1-based
    m = len(order)
    tree = [0] * (m + 1)
    out = []
    append = out.append
    for v in values:
        i = rank[v] - 1                                   # count ranks < v
        s = 0
        while i:
            s += tree[i]
            i -= i & -i
        append(s)
        i = rank[v]
        while i <= m:
            tree[i] += 1
            i += i & -i
    return out


def _count_smaller_insort(values):
    """Generic path: sorted list of what has been seen so far."""
    seen = []
    out = []
    for v in values:
        out.append(bisect.bisect_left(seen, v))           # strictly smaller
        bisect.insort(seen, v)
    return out


# --------------------------------------------------------------------------
# independent second implementation (merge sort), used to cross-check fast
# --------------------------------------------------------------------------
def count_smaller_before_merge(values):
    vals = list(values)
    n = len(vals)
    counts = [0] * n

    def sort_ids(ids):
        length = len(ids)
        if length <= 1:
            return ids
        mid = length // 2
        left = sort_ids(ids[:mid])
        right = sort_ids(ids[mid:])
        out = []
        i = j = 0
        smaller_from_left = 0
        while i < len(left) and j < len(right):
            if vals[left[i]] < vals[right[j]]:
                out.append(left[i])
                i += 1
                smaller_from_left += 1
            else:
                counts[right[j]] += smaller_from_left
                out.append(right[j])
                j += 1
        if i < len(left):
            out.extend(left[i:])
        else:
            for r in right[j:]:        # left is exhausted: every remaining
                counts[r] += smaller_from_left      # right element sees them all
            out.extend(right[j:])
        return out

    sort_ids(list(range(n)))
    return counts


# --------------------------------------------------------------------------
# correctness
# --------------------------------------------------------------------------
def correctness_rounds(rounds=400):
    rng = random.Random(1234)
    generators = [
        ("random ints -100..100", lambda k: [rng.randint(-100, 100) for _ in range(k)]),
        ("random ints -10..10 (heavy duplicates)", lambda k: [rng.randint(-10, 10) for _ in range(k)]),
        ("all equal", lambda k: [7] * k),
        ("all equal negative", lambda k: [-3] * k),
        ("sorted ascending", lambda k: list(range(k))),
        ("sorted descending", lambda k: list(range(k, 0, -1))),
        ("negatives only", lambda k: [-rng.randint(1, 50) for _ in range(k)]),
        ("with zeros", lambda k: [rng.choice([0, 0, 1, -1]) for _ in range(k)]),
        ("single huge + tiny", lambda k: [rng.choice([-10**18, 10**18, 0]) for _ in range(k)]),
        ("floats", lambda k: [round(rng.uniform(-20, 20), 3) for _ in range(k)]),
        ("empty-ish", lambda k: [] if rng.random() < 0.5 else [rng.randint(-5, 5)]),
    ]
    checked = 0
    failures = []
    for label, gen in generators:
        for _ in range(rounds // len(generators) + 1):
            k = rng.randint(0, 40)
            vals = gen(k)
            expected = count_smaller_before(vals)
            fast = count_smaller_before_fast(vals)
            merge = count_smaller_before_merge(vals)
            checked += 1
            if fast != expected or merge != expected:
                failures.append((label, vals, expected, fast, merge))
    # edge cases explicitly
    for vals in ([], [0], [-1], [5, 5], [-1, -1, -1], [3, 1, 2], [2, 2, 1, 3, 3, 0]):
        checked += 1
        expected = count_smaller_before(vals)
        if count_smaller_before_fast(vals) != expected or count_smaller_before_merge(vals) != expected:
            failures.append(("edge", vals, expected, None, None))
    return checked, failures


def cross_check_large(size, seed):
    """Two independent O(n log n) implementations on one big input."""
    rng = random.Random(seed)
    vals = [rng.randint(-size, size) for _ in range(size)]
    a = count_smaller_before_fast(vals)
    b = count_smaller_before_merge(vals)
    return a == b, sum(a), size


def cross_check_insort(size, seed):
    """The generic (non-int) path against the original, on a smaller input."""
    rng = random.Random(seed)
    vals = [round(rng.uniform(-size, size), 4) for _ in range(size)]
    return (_count_smaller_insort(vals) == count_smaller_before(vals)
            == count_smaller_before_merge(vals) == count_smaller_before_fast(vals))


# --------------------------------------------------------------------------
# timings
# --------------------------------------------------------------------------
def timeit(fn, values, reps=1):
    best = None
    for _ in range(reps):
        t0 = time.perf_counter()
        fn(values)
        dt = time.perf_counter() - t0
        best = dt if best is None else min(best, dt)
    return best


def main():
    print("machine: python %s" % __import__("sys").version.split()[0])
    print()
    print("=" * 72)
    print("correctness")
    print("=" * 72)
    checked, failures = correctness_rounds()
    print(f"  random + edge cases checked against the original: {checked}")
    print(f"  mismatches (fast vs original, merge vs original): {len(failures)}")
    for f in failures[:3]:
        print("   ", f)
    for size in (20_000, 200_000):
        agree, total, n = cross_check_large(size, seed=size)
        print(f"  size {size:>7}: Fenwick == merge-sort: {agree} "
              f"(sum of all counts = {total})")
    for size in (500, 5_000):
        print(f"  size {size:>7}: float input, original == Fenwick == merge == bisect: "
              f"{cross_check_insort(size, seed=size)}")

    print()
    print("=" * 72)
    print("timings (best of 3, same input for both versions)")
    print("=" * 72)
    rng = random.Random(99)
    print(f"  {'n':>9}  {'original s':>13}  {'replacement s':>14}")
    measured = {}
    for n, reps in ((1_000, 3), (2_000, 3), (5_000, 2), (10_000, 1), (20_000, 1)):
        vals = [rng.randint(-n, n) for _ in range(n)]
        t_orig = timeit(count_smaller_before, vals, reps)
        t_new = timeit(count_smaller_before_fast, vals, 3)
        measured[n] = (t_orig, t_new)
        print(f"  {n:>9}  {t_orig:>13.4f}  {t_new:>14.5f}   (original reps={reps})")
    for n in (50_000, 200_000, 1_000_000):
        vals = [rng.randint(-n, n) for _ in range(n)]
        t_new = timeit(count_smaller_before_fast, vals, 3)
        print(f"  {n:>9}  {'(not measured)':>13}  {t_new:>14.5f}")
    # extrapolation evidence from the two largest measured original runs
    print()
    r1 = measured[20_000][0] / measured[10_000][0]
    t20 = measured[20_000][0]
    print(f"  original: 10_000 -> 20_000 time ratio = {r1:.2f} (quadratic behaviour confirmed)")
    print(f"  original at 20_000 = {t20:.3f}s, so 200_000 (100x the input) projects to "
          f"about {t20 * 100 * 100 / 60:.0f} minutes")
    print(f"  replacement at 20_000 = {measured[20_000][1]*1000:.1f} ms")


if __name__ == "__main__":
    main()
