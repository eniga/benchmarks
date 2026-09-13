"""C4: optimize count_smaller_before.

Original is O(n^2) (a fresh linear scan for every element). For n = 200,000
that is ~4e10 operations -- far too slow.

Optimized approach: Fenwick tree (Binary Indexed Tree) over coordinate-compressed
values, giving O(n log n).

  * Coordinate compression maps the (possibly negative, possibly duplicated)
    values to ranks 1..m in sorted order. This handles negatives and duplicates.
  * Scanning left to right, for value v with rank r:
        smaller_so_far = prefix_sum(r - 1)   # count of values with rank < r
      then update(r, +1).
  * "Strictly smaller" is exactly "rank strictly less", so duplicates are
    handled correctly (equal values do not count).

The optimized function returns the same list as the original for any input.
"""

import random
import time


# ---------------------------------------------------------------------------
# Original (O(n^2))
# ---------------------------------------------------------------------------

def count_smaller_before(nums):
    out = []
    for i in range(len(nums)):
        c = 0
        for j in range(i):
            if nums[j] < nums[i]:
                c += 1
        out.append(c)
    return out


# ---------------------------------------------------------------------------
# Optimized (O(n log n))
# ---------------------------------------------------------------------------

def count_smaller_before_fast(nums):
    n = len(nums)
    if n == 0:
        return []

    # Coordinate compression: rank each distinct value 1..m in sorted order.
    sorted_unique = sorted(set(nums))
    rank = {v: i + 1 for i, v in enumerate(sorted_unique)}
    m = len(sorted_unique)

    # Fenwick tree (1-indexed) over the ranks.
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
        out[idx] = query(r - 1)   # strictly smaller = rank < r
        update(r)
    return out


# ---------------------------------------------------------------------------
# Equivalence + timing
# ---------------------------------------------------------------------------

def check_equivalence():
    rng = random.Random(20240614)
    worst = 0
    for trial in range(400):
        n = rng.randint(0, 60)
        # small value range to force lots of duplicates
        lo, hi = -rng.randint(0, 5), rng.randint(0, 5)
        nums = [rng.randint(lo, hi) for _ in range(n)]
        a = count_smaller_before(nums)
        b = count_smaller_before_fast(nums)
        if a != b:
            print(f"MISMATCH on {nums}\n  orig={a}\n  fast={b}")
            return False
    # a few larger structured cases
    for nums in (
        list(range(200)),                 # strictly increasing
        list(range(200, 0, -1)),          # strictly decreasing
        [5] * 200,                        # all equal
        [rng.randint(-1000, 1000) for _ in range(2000)],
        [rng.choice([1, 2, 3]) for _ in range(3000)],   # heavy duplicates
    ):
        if count_smaller_before(nums) != count_smaller_before_fast(nums):
            print(f"MISMATCH on structured case len={len(nums)}")
            return False
    print("equivalence: original == optimized on all randomized + structured "
          "inputs (incl. negatives and duplicates)")
    return True


def time_original():
    # Largest n the O(n^2) original can do in a reasonable time.
    rng = random.Random(1)
    for n in (1000, 2000, 4000, 8000, 16000, 20000):
        nums = [rng.randint(-10**9, 10**9) for _ in range(n)]
        t0 = time.perf_counter()
        count_smaller_before(nums)
        dt = time.perf_counter() - t0
        print(f"  original n={n:>6}: {dt:8.3f}s")
        if dt > 4.0:
            break


def time_optimized():
    rng = random.Random(1)
    n = 200_000
    nums = [rng.randint(-10**9, 10**9) for _ in range(n)]
    # warm-up / JIT-free steady state: run a few times, take the best
    best = float("inf")
    result = None
    for _ in range(3):
        t0 = time.perf_counter()
        result = count_smaller_before_fast(nums)
        dt = time.perf_counter() - t0
        best = min(best, dt)
    # sanity: a spot check against the original on a prefix
    prefix = 2000
    assert count_smaller_before(nums[:prefix]) == result[:prefix]
    print(f"  optimized n={n:>6}: {best:8.3f}s  (best of 3, under 2s: "
          f"{best < 2.0})")
    return best


def main():
    ok = check_equivalence()
    print("\ntiming (original, O(n^2)):")
    time_original()
    print("\ntiming (optimized, O(n log n)):")
    best = time_optimized()
    ok = ok and best < 2.0
    print("\n" + ("C4 COMPLETE: equivalent and fast" if ok
                  else "C4 INCOMPLETE"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
