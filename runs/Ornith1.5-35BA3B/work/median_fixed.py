"""Fixed median_of_sorted_arrays and verification against a brute force.

Fix rationale
-------------
The original computes the even-total median as
    (max(left_a, left_b) + min(right_a, right_b)) / 2
In Python 3 the `/` operator does true division: the integer sum is converted to
a ``float`` before dividing.  For small values (unit tests) the result is exact,
but when the two middle record IDs are large 64-bit integers their sum exceeds
2**53 and can no longer be represented exactly, so the returned float is rounded
-> "wrong median in production".  The odd-total branch returns an int and is
unaffected, which is why the failure is intermittent / value-dependent.

The fix performs the average with exact integer arithmetic and returns an int
when the median is integral and a ``Fraction`` otherwise, so no value is ever
rounded.
"""

from fractions import Fraction
from typing import List


def median_of_sorted_arrays(a: List[int], b: List[int]):
    if len(a) > len(b):
        a, b = b, a
    lo, hi = 0, len(a)
    n = len(a) + len(b)
    while lo <= hi:
        i = (lo + hi) // 2
        j = (n + 1) // 2 - i
        left_a  = a[i - 1] if i > 0 else float('-inf')
        right_a = a[i]     if i < len(a) else float('inf')
        left_b  = b[j - 1] if j > 0 else float('-inf')
        right_b = b[j]     if j < len(b) else float('inf')
        if left_a <= right_b and left_b <= right_a:
            if n % 2:
                return max(left_a, left_b)
            left = max(left_a, left_b)
            right = min(right_a, right_b)
            total = left + right
            if total % 2 == 0:
                return total // 2          # exact integer median
            return Fraction(total, 2)      # exact half-integer median
        elif left_a > right_b:
            hi = i - 1
        else:
            lo = i + 1
    raise RuntimeError("unreachable for well-formed sorted inputs")


def brute_force_median(a: List[int], b: List[int]):
    merged = sorted(a + b)
    n = len(merged)
    if n % 2:
        return merged[n // 2]
    s = merged[n // 2 - 1] + merged[n // 2]
    return s // 2 if s % 2 == 0 else Fraction(s, 2)


def main():
    import random

    # The exact input that broke the original.
    a = [2 ** 62, 2 ** 62 + 2]
    b = [2 ** 62 + 4, 2 ** 62 + 6]
    print("fixed result :", median_of_sorted_arrays(a[:], b[:]))
    print("exact median :", brute_force_median(a, b))

    print()
    print("=== fuzz vs brute force (small + 64-bit) ===")
    bad = 0
    total = 0
    for _ in range(200000):
        la = random.randint(1, 5); lb = random.randint(1, 5)
        regime = random.random() < 0.5
        if regime:
            base = random.randint(0, 2 ** 60)
            a = sorted(base + random.randint(0, 20) for _ in range(la))
            b = sorted(base + random.randint(0, 20) for _ in range(lb))
        else:
            a = sorted(random.randint(0, 10 ** 6) for _ in range(la))
            b = sorted(random.randint(0, 10 ** 6) for _ in range(lb))
        got = median_of_sorted_arrays(a[:], b[:])
        exp = brute_force_median(a, b)
        total += 1
        if Fraction(got) != exp:
            bad += 1
            if bad <= 5:
                print("  MISMATCH", a, b, got, exp)
    print(f"  mismatches: {bad} / {total}")


if __name__ == "__main__":
    main()
