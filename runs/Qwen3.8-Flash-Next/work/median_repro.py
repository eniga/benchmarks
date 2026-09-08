"""Reproduce and diagnose the reported median_of_sorted_arrays bug.

The function under investigation is copied verbatim from the report.
`exact_median` is an independent reference implementation that never converts
an integer to a float.
"""

import random
from fractions import Fraction


def median_of_sorted_arrays(a, b):
    if len(a) > len(b):
        a, b = b, a
    lo, hi = 0, len(a)
    while lo <= hi:
        i = (lo + hi) // 2
        j = (len(a) + len(b) + 1) // 2 - i
        left_a  = a[i-1] if i > 0 else float('-inf')
        right_a = a[i]   if i < len(a) else float('inf')
        left_b  = b[j-1] if j > 0 else float('-inf')
        right_b = b[j]   if j < len(b) else float('inf')
        if left_a <= right_b and left_b <= right_a:
            if (len(a) + len(b)) % 2:
                return max(left_a, left_b)
            return (max(left_a, left_b) + min(right_a, right_b)) / 2
        elif left_a > right_b:
            hi = i - 1
        else:
            lo = i + 1


def sorted_cat(a, b):
    out = []
    i = j = 0
    while i < len(a) and j < len(b):
        if a[i] <= b[j]:
            out.append(a[i]); i += 1
        else:
            out.append(b[j]); j += 1
    out.extend(a[i:])
    out.extend(b[j:])
    return out


def exact_median(a, b):
    """Median of two sorted sequences, exact for arbitrarily large integers."""
    merged = sorted_cat(a, b)
    n = len(merged)
    if n == 0:
        raise ValueError("empty")
    if n % 2:
        return merged[n // 2]
    lo, hi = merged[n // 2 - 1], merged[n // 2]
    s = lo + hi
    if isinstance(lo, int) and isinstance(hi, int) and not isinstance(lo, bool):
        return s // 2 if s % 2 == 0 else Fraction(s, 2)
    return s / 2


def rand_sorted(rng, n, lo, hi):
    return sorted(rng.randint(lo, hi) for _ in range(n))


def trial(rng, value_lo, value_hi, max_len=12):
    la = rng.randint(0, max_len)
    lb = rng.randint(0, max_len)
    if la + lb == 0:
        lb = 1
    a = rand_sorted(rng, la, value_lo, value_hi)
    b = rand_sorted(rng, lb, value_lo, value_hi)
    return a, b


def sweep(label, value_lo, value_hi, rounds=5000, seed=0):
    rng = random.Random(seed)
    fails = []
    for _ in range(rounds):
        a, b = trial(rng, value_lo, value_hi)
        try:
            got = median_of_sorted_arrays(list(a), list(b))
        except Exception as exc:  # noqa: BLE001
            got = f"raised {type(exc).__name__}: {exc}"
        want = exact_median(a, b)
        same = (got == want) if not isinstance(got, str) else False
        if not same:
            fails.append((a, b, got, want))
    print(f"{label}: {len(fails)}/{rounds} mismatches")
    return fails


if __name__ == "__main__":
    small = sweep("small ids 0..50", 0, 50)
    mid = sweep("32-bit ids", 0, 2**31 - 1)
    big = sweep("64-bit ids near 2**63", 2**63 - 10**12, 2**63 - 1)

    print()
    print("First mismatching case from the 64-bit sweep:")
    if big:
        a, b, got, want = big[0]
        print(f"  a = {a}")
        print(f"  b = {b}")
        print(f"  returned {got!r} ({type(got).__name__})")
        print(f"  exact    {want!r} ({type(want).__name__}) = {float(want):f}")
        print(f"  abs error {float(abs(Fraction(want) - Fraction(got)))}")

    print()
    print("Edge cases:")
    print("  empty inputs        ->", repr(median_of_sorted_arrays([], [])))
    print("  one empty           ->", repr(median_of_sorted_arrays([], [1, 2, 3])))
    print("  small even case     ->", repr(median_of_sorted_arrays([1, 2], [3, 4])))
