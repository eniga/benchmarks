"""Reproduce the 64-bit median bug and verify the fix."""

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


def fixed_median_of_sorted_arrays(a, b):
    """Same O(log n) partition search, but the even-length median is
    computed with exact integer arithmetic: an int when the median is an
    integer, a Fraction (exact .5) otherwise. No float is ever formed from
    the data values."""
    if len(a) > len(b):
        a, b = b, a
    n = len(a) + len(b)
    if n == 0:
        return None
    lo, hi = 0, len(a)
    while lo <= hi:
        i = (lo + hi) // 2
        j = (n + 1) // 2 - i
        left_a  = a[i-1] if i > 0 else float('-inf')
        right_a = a[i]   if i < len(a) else float('inf')
        left_b  = b[j-1] if j > 0 else float('-inf')
        right_b = b[j]   if j < len(b) else float('inf')
        if left_a <= right_b and left_b <= right_a:
            if n % 2:
                return max(left_a, left_b)
            x, y = max(left_a, left_b), min(right_a, right_b)
            s = x + y
            if s % 2 == 0:
                return s // 2
            return Fraction(s, 2)
        elif left_a > right_b:
            hi = i - 1
        else:
            lo = i + 1


def exact_median(a, b):
    s = sorted(a + b)
    n = len(s)
    if n % 2:
        return Fraction(s[n // 2])
    return Fraction(s[n // 2 - 1] + s[n // 2], 2)


# ---------------------------------------------------------------- repro
a = [9223372036854775806]   # 2**63 - 2
b = [9223372036854775807]   # 2**63 - 1
print("repro input: a =", a, " b =", b)
print("original returns:", repr(median_of_sorted_arrays(a, b)))
print("fixed    returns:", repr(fixed_median_of_sorted_arrays(a, b)))
print("exact median:    9223372036854775806.5")
print()

# a second repro: even length, large ids, both on one side of 2**63
a2 = [18446744073709551614, 18446744073709551615]  # 2**64-2, 2**64-1
b2 = []
print("repro input: a =", a2, " b =", b2)
print("original returns:", repr(median_of_sorted_arrays(a2, b2)))
print("fixed    returns:", repr(fixed_median_of_sorted_arrays(a2, b2)))
print("exact median:    18446744073709551614.5")
print()

# ------------------------------------------------- randomized verification
random.seed(42)
checked = 0
for _ in range(20000):
    la = random.randint(0, 12)
    lb = random.randint(0, 12)
    if la + lb == 0:
        continue
    # 64-bit record-id magnitude values
    a = sorted(random.getrandbits(64) for _ in range(la))
    b = sorted(random.getrandbits(64) for _ in range(lb))
    got = fixed_median_of_sorted_arrays(a, b)
    want = exact_median(a, b)
    assert Fraction(got) == want, (a, b, got, want)
    checked += 1
print(f"randomized 64-bit trials passed: {checked}")

# small-value regression check (the cases that passed in unit tests)
small_cases = [
    ([1, 3], [2]),
    ([1, 2], [3, 4]),
    ([], [5]),
    ([1, 2, 3, 4], []),
    ([2, 2], [2]),
]
for a, b in small_cases:
    got = fixed_median_of_sorted_arrays(a, b)
    want = exact_median(a, b)
    assert Fraction(got) == want, (a, b, got, want)
print("small-value regression cases passed")
