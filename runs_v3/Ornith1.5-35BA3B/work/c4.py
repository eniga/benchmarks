"""C4: speed up count_smaller_before while keeping behaviour identical.

Original is O(n^2). New version is O(n log n) using a Fenwick (binary indexed)
tree over coordinate-compressed values.

Strictly-less-than semantics are preserved: for index i we count j < i with
values[j] < values[i]. With 1-based ranks, "strictly less than v" is the prefix
sum of inserted counts for ranks 1..(rank(v)-1).
"""

import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))


def count_smaller_before(values):
    """Reference (slow) implementation."""
    out = []
    for i, v in enumerate(values):
        n = 0
        for j in range(i):
            if values[j] < v:
                n += 1
        out.append(n)
    return out


def count_smaller_before_fast(values):
    """O(n log n) implementation with identical results."""
    if not values:
        return []
    # Coordinate compression to 1-based ranks over the sorted unique values.
    sorted_unique = sorted(set(values))
    rank = {v: i + 1 for i, v in enumerate(sorted_unique)}
    m = len(sorted_unique)
    bit = [0] * (m + 1)

    def update(i):
        while i <= m:
            bit[i] += 1
            i += i & (-i)

    def query(i):
        s = 0
        while i > 0:
            s += bit[i]
            i -= i & (-i)
        return s

    out = []
    append = out.append
    for v in values:
        r = rank[v]
        append(query(r - 1))      # count of already-seen values strictly less
        update(r)
    return out


def test_equivalence():
    rng = random.Random(12345)
    trials = 0
    # Varied distributions: duplicates, negatives, small ranges, large ranges.
    for _ in range(3000):
        n = rng.randint(0, 60)
        kind = rng.choice(["dense", "neg", "uniq", "wide", "allsame"])
        if kind == "dense":
            vals = [rng.randint(0, 3) for _ in range(n)]
        elif kind == "neg":
            vals = [rng.randint(-50, 50) for _ in range(n)]
        elif kind == "uniq":
            vals = rng.sample(range(-1000, 1000), n)
        elif kind == "wide":
            vals = [rng.randint(-10**9, 10**9) for _ in range(n)]
        else:  # allsame
            vals = [rng.randint(-5, 5)] * n
        a = count_smaller_before(vals)
        b = count_smaller_before_fast(vals)
        assert a == b, (vals, a, b)
        trials += 1
    print("equivalence trials passed:", trials)

    # A few hand-checkable cases.
    cases = [
        ([5, 2, 2, 10, 1], [0, 0, 0, 3, 0]),
        ([], []),
        ([7], [0]),
        ([3, 3, 3], [0, 0, 0]),
        ([1, 2, 3, 4, 5], [0, 1, 2, 3, 4]),
        ([5, 4, 3, 2, 1], [0, 0, 0, 0, 0]),
        ([-1, -2, 0, 3, -2], [0, 0, 2, 3, 0]),
    ]
    for vals, expected in cases:
        got = count_smaller_before_fast(vals)
        assert got == expected, (vals, got, expected)
    print("hand-checked cases passed")


def bench(fn, values, label, budget_s=3.0):
    t0 = time.perf_counter()
    result = fn(values)
    dt = time.perf_counter() - t0
    print(f"  {label}: n={len(values):,}  time={dt:.4f}s  "
          f"(result[0:3]={result[:3]})")
    return dt, result


def main():
    print("=== Correctness ===")
    test_equivalence()

    print()
    print("=== Benchmark: original O(n^2) (largest size that finishes in budget) ===")
    rng = random.Random(99)
    # Grow the size until the original exceeds the time budget.
    largest_ok = None
    best_dt = None
    last_size = None
    last_dt = None
    size = 2000
    while size <= 200_000:
        vals = [rng.randint(-10**9, 10**9) for _ in range(size)]
        t0 = time.perf_counter()
        count_smaller_before(vals)
        dt = time.perf_counter() - t0
        last_size, last_dt = size, dt
        if dt > 3.0:
            print(f"  n={size:,}: {dt:.3f}s  (over budget, stopping)")
            break
        print(f"  n={size:,}: {dt:.4f}s")
        largest_ok = size
        best_dt = dt
        size *= 2

    if largest_ok is None:
        print("  original finished every size up to 200,000")

    print()
    print("=== Benchmark: new O(n log n) at 200,000 (the target size) ===")
    target = [rng.randint(-10**9, 10**9) for _ in range(200_000)]
    t0 = time.perf_counter()
    fast_result = count_smaller_before_fast(target)
    fast_dt = time.perf_counter() - t0
    print(f"  FAST n=200,000: {fast_dt:.4f}s  result[:3]={fast_result[:3]}")

    # Prove the fast result equals the original at a size the original can handle.
    check_n = largest_ok if largest_ok is not None else 4000
    chk = [rng.randint(-1000, 1000) for _ in range(check_n)]
    assert count_smaller_before_fast(chk) == count_smaller_before(chk)
    print(f"  fast == original at n={check_n:,}: OK")

    if largest_ok is not None:
        # Extrapolate original to 200,000 using the O(n^2) scaling, clearly labeled.
        scale = (200_000 / largest_ok) ** 2
        est = best_dt * scale
        print()
        print(f"=== Summary ===")
        print(f"  original O(n^2) measured, under 3s budget: n={largest_ok:,} "
              f"({best_dt:.4f}s)")
        print(f"  original O(n^2) actually measured (over 3s budget): n={last_size:,} "
              f"({last_dt:.4f}s); NOT run at 200,000")
        print(f"  (extrapolated O(n^2) estimate for original at 200,000: ~{est:.1f}s "
              f"-- not actually run)")
        print(f"  new O(n log n) measured at n=200,000: {fast_dt:.4f}s")
        print(f"  complexity: original O(n^2), new O(n log n)")


if __name__ == "__main__":
    main()
