"""Reproduce the median_of_sorted_arrays production bug (tools section I2)."""

import random
from itertools import combinations
from typing import List


def median_of_sorted_arrays(a, b):
    # verbatim from the task
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


def brute_force_median(a: List[int], b: List[int]):
    merged = sorted(a + b)
    n = len(merged)
    if n % 2:
        return merged[n // 2]
    left, right = merged[n // 2 - 1], merged[n // 2]
    s = left + right
    # exact median value (integer or half-integer)
    if s % 2 == 0:
        return s // 2
    from fractions import Fraction
    return Fraction(s, 2)


def exact_equal(got, exp):
    from fractions import Fraction
    if isinstance(exp, Fraction):
        # got is a float; compare with tolerance to expose precision loss
        if isinstance(got, float):
            return abs(got - float(exp)) < 1e-3 and abs(got - float(exp)) > 1e-9
        return Fraction(got) == exp
    return got == exp


def main():
    print("=== Deterministic 64-bit reproduction ===")
    a = [2 ** 62, 2 ** 62 + 2]
    b = [2 ** 62 + 4, 2 ** 62 + 6]
    got = median_of_sorted_arrays(a, b)
    exp = brute_force_median(a, b)
    print(f"a={a}")
    print(f"b={b}")
    print(f"function returned: {got!r}  (type {type(got).__name__})")
    print(f"exact median     : {exp!r}  (type {type(exp).__name__})")
    print(f"exact as float   : {float(exp)!r}")
    print(f"MISMATCH: {got!r} != {exp!r}")

    print()
    print("=== Why small numbers pass but 64-bit fails ===")
    small_a, small_b = [1, 3], [2, 4]
    print(f"small {small_a},{small_b}: fn={median_of_sorted_arrays(small_a, small_b)!r} exact={brute_force_median(small_a, small_b)!r}")
    print("  -> (3+... ) the average of two small ints is exactly representable as float")
    print(f"  -> sum of 64-bit middles = {2**62+2 + 2**62+4} = 2**63+6 > 2**53, so /2 rounds in float")

    print("=== Fuzz: small ints (unit-test regime) ===")
    bad = 0
    for _ in range(20000):
        la = random.randint(1, 4); lb = random.randint(1, 4)
        a = sorted(random.randint(0, 1000) for _ in range(la))
        b = sorted(random.randint(0, 1000) for _ in range(lb))
        got = median_of_sorted_arrays(a, b)
        exp = brute_force_median(a, b)
        if isinstance(exp, int):
            if got != exp:
                bad += 1
                print("  small int mismatch", a, b, got, exp)
        else:
            if abs(got - float(exp)) > 1e-9:
                bad += 1
                print("  small half mismatch", a, b, got, exp)
    print(f"  mismatches: {bad}")

    print()
    print("=== Fuzz: 64-bit record IDs (production regime) ===")
    bad = 0
    examples = []
    for _ in range(20000):
        la = random.randint(1, 4); lb = random.randint(1, 4)
        base = random.randint(0, 2 ** 60)
        a = sorted(base + random.randint(0, 10) for _ in range(la))
        b = sorted(base + random.randint(0, 10) for _ in range(lb))
        got = median_of_sorted_arrays(a, b)
        exp = brute_force_median(a, b)
        ok = exact_equal(got, exp)
        if not ok:
            bad += 1
            if len(examples) < 5:
                examples.append((a, b, got, exp))
    for a, b, got, exp in examples:
        print(f"  a={a} b={b} fn={got!r} exact={exp!r} float(exact)={float(exp)!r}")
    print(f"  mismatches: {bad} / 20000")


if __name__ == "__main__":
    main()
