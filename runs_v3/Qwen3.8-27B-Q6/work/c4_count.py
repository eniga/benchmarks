"""C4: optimize count_smaller_before, prove identical results, report timings."""

import random
import time


def count_smaller_before(values):
    """Original: O(n^2)."""
    out = []
    for i, v in enumerate(values):
        c = 0
        for j in range(i):
            if values[j] < v:
                c += 1
        out.append(c)
    return out


def count_smaller_before_fast(values):
    """Fenwick tree (BIT) over coordinate-compressed values: O(n log n).

    For each i, the answer is the number of earlier elements strictly less
    than values[i]. We query the BIT prefix sum over ranks < rank(values[i])
    (which counts earlier strictly-smaller values), then add values[i].
    """
    if not values:
        return []
    # Coordinate compression (order-preserving; duplicates share a rank).
    sorted_unique = sorted(set(values))
    rank = {v: i + 1 for i, v in enumerate(sorted_unique)}  # 1-indexed
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
    for v in values:
        r = rank[v]
        out.append(query(r - 1))  # earlier values with rank < r  => strictly smaller
        update(r)
    return out


def verify(seed=0, trials=200, max_n=60):
    rng = random.Random(seed)
    for t in range(trials):
        n = rng.randint(0, max_n)
        # Mix of small ranges (many duplicates) and wide ranges, incl. negatives.
        style = t % 4
        if style == 0:
            vals = [rng.randint(0, 3) for _ in range(n)]          # heavy dupes
        elif style == 1:
            vals = [rng.randint(-50, 50) for _ in range(n)]        # negatives+dupes
        elif style == 2:
            vals = [rng.randint(-10**9, 10**9) for _ in range(n)]  # wide, ~unique
        else:
            vals = [rng.choice([7, 7, 7, -2, 0, 10**9]) for _ in range(n)]
        a = count_smaller_before(vals)
        b = count_smaller_before_fast(vals)
        if a != b:
            print(f"MISMATCH trial {t} n={n}\n vals={vals}\n orig={a}\n fast={b}")
            return False
    print(f"verify: {trials} randomized trials (n up to {max_n}, dupes+negatives) "
          f"-> identical results")
    return True


def timed(fn, values, label):
    t0 = time.perf_counter()
    res = fn(values)
    dt = time.perf_counter() - t0
    print(f"  {label}: n={len(values):,}  {dt:.3f}s  (sum={sum(res):,})")
    return dt


if __name__ == "__main__":
    ok = verify()
    # A couple of deterministic spot checks.
    assert count_smaller_before_fast([5, 2, 6, 1]) == [0, 0, 2, 0]
    assert count_smaller_before_fast([2, 2, 2]) == [0, 0, 0]
    assert count_smaller_before_fast([]) == []
    assert count_smaller_before_fast([3]) == [0]
    print("deterministic spot checks OK")
    print()

    print("=== timings ===")
    # Original is O(n^2); measure it at a size that is still tractable.
    rng = random.Random(42)
    for n in (1000, 2000, 4000):
        vals = [rng.randint(-10**9, 10**9) for _ in range(n)]
        timed(count_smaller_before, vals, "original O(n^2)")
    print("  (original at n=200,000 would be ~ (200000/4000)^2 = 2500x the "
          "n=4000 time; not measured because it is far too slow)")
    print()
    # Fast version at the required size.
    big = [rng.randint(-10**9, 10**9) for _ in range(200_000)]
    timed(count_smaller_before_fast, big, "fast O(n log n)")

    # Cross-check the fast version against the original at a moderate size.
    mid = [rng.randint(-10**6, 10**6) for _ in range(5000)]
    assert count_smaller_before(mid) == count_smaller_before_fast(mid)
    print("cross-check at n=5,000: original == fast")
    print()
    print("ALL C4 CHECKS PASSED" if ok else "C4 VERIFY FAILED")
