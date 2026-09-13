"""C4: original O(n^2) vs Fenwick-tree O(n log n) count_smaller_before."""

import random
import time


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


def count_smaller_fast(values):
    """Fenwick tree over coordinate-compressed ranks. O(n log n)."""
    n = len(values)
    if n == 0:
        return []
    uniq = sorted(set(values))
    rank = {v: i + 1 for i, v in enumerate(uniq)}
    m = len(uniq)
    tree = [0] * (m + 1)
    out = [0] * n
    for i, v in enumerate(values):
        r = rank[v]
        s = 0
        j = r - 1
        while j:
            s += tree[j]
            j -= j & -j
        out[i] = s
        j = r
        while j <= m:
            tree[j] += 1
            j += j & -j
    return out


def main():
    random.seed(20260913)

    # --- equivalence: randomised, duplicates, negatives ---
    trials = 0
    for _ in range(300):
        n = random.randint(0, 400)
        style = random.choice(("wide", "dup", "neg", "mixed"))
        if style == "wide":
            data = [random.randint(-10**9, 10**9) for _ in range(n)]
        elif style == "dup":
            data = [random.randint(0, 5) for _ in range(n)]
        elif style == "neg":
            data = [random.randint(-50, -1) for _ in range(n)]
        else:
            data = [random.choice([7, 7, -3, 0, 42, -10**6]) for _ in range(n)]
        if count_smaller_before(data) != count_smaller_fast(data):
            print("MISMATCH on", data)
            return
        trials += 1
    for edge in ([], [1], [5, 5, 5], [3, 1, 2], [-1, -2, -3], [2, 1, 2, 1]):
        assert count_smaller_before(edge) == count_smaller_fast(edge), edge
    print(f"equivalence: {trials} random trials + 6 edge cases, all identical")

    # --- timings ---
    sizes_orig = [2000, 5000, 10000]
    print("\noriginal O(n^2):")
    for n in sizes_orig:
        data = [random.randint(0, 10**6) for _ in range(n)]
        t0 = time.perf_counter()
        count_smaller_before(data)
        dt = time.perf_counter() - t0
        print(f"  n={n:>7}: {dt:8.3f}s")

    big = [random.randint(0, 10**6) for _ in range(200_000)]
    t0 = time.perf_counter()
    r = count_smaller_fast(big)
    dt = time.perf_counter() - t0
    print(f"\nFenwick O(n log n): n=200000: {dt:.3f}s  (result len {len(r)})")
    # spot-check the big run against the original on a 2000 prefix
    assert r[:2000] == count_smaller_before(big[:2000])
    print("spot-check: first 2000 entries of the 200k run match the original")


if __name__ == "__main__":
    main()
