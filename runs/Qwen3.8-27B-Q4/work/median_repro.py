"""Reproduce the median bug with 64-bit record IDs and verify the fix."""

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


def median_of_sorted_arrays_fixed(a, b):
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
            total = max(left_a, left_b) + min(right_a, right_b)
            if total % 2 == 0:
                return total // 2
            return Fraction(total, 2)
        elif left_a > right_b:
            hi = i - 1
        else:
            lo = i + 1


def naive_median(a, b):
    merged = sorted(a + b)
    n = len(merged)
    if n % 2:
        return Fraction(merged[n // 2])
    total = merged[n // 2 - 1] + merged[n // 2]
    if total % 2 == 0:
        return Fraction(total // 2)
    return Fraction(total, 2)


print("=== 1. Small values: original passes (why unit tests see no bug) ===")
small_cases = [
    ([1, 3], [2]),
    ([1, 2], [3, 4]),
    ([], [1, 2, 3]),
    ([100], [200, 300]),
    ([1, 3, 5, 7], [2, 4, 6, 8, 100]),
]
for a, b in small_cases:
    print(f"  a={a} b={b}: original={median_of_sorted_arrays(a, b)!r} "
          f"expected={naive_median(a, b)!r}")

print()
print("=== 2. 64-bit record IDs: original is wrong ===")
a = [2**62]
b = [2**62 + 2]
got = median_of_sorted_arrays(a, b)
want = naive_median(a, b)
print(f"  a={a}")
print(f"  b={b}")
print(f"  original returned: {got!r}  (exact value of that float: {Fraction(got)})")
print(f"  correct median:    {int(want)}")
print(f"  wrong? {Fraction(got) != want}   (exact error: {Fraction(got) - want})")

print()
print("=== 3. More 64-bit cases ===")
cases64 = [
    ([2**63 - 1, 2**63], [2**63 - 2]),
    ([9_223_372_036_854_775_807], [9_223_372_036_854_775_806]),
    ([2**62, 2**62 + 4], [2**62 + 1, 2**62 + 3]),
    ([2**63 - 10, 2**63 - 8, 2**63 - 6], [2**63 - 9, 2**63 - 7, 2**63 - 5, 2**63 - 3]),
]
for a, b in cases64:
    got = median_of_sorted_arrays(a, b)
    want = naive_median(a, b)
    fixed = median_of_sorted_arrays_fixed(a, b)
    print(f"  a={a} b={b}")
    print(f"    original={got!r}  correct={int(want) if want.denominator == 1 else str(want)}  "
          f"fixed={fixed!r}  fixed_ok={Fraction(fixed) == want}")

print()
print("=== 4. Randomized cross-check of the fixed version (5000 cases) ===")
random.seed(42)
fails = 0
for trial in range(5000):
    n = random.randint(0, 40)
    m = random.randint(0, 40)
    # mix small values and 64-bit-scale values
    scale = random.choice([10, 10**6, 2**63])
    a = sorted(random.randrange(0, scale) for _ in range(n))
    b = sorted(random.randrange(0, scale) for _ in range(m))
    if not a and not b:
        continue
    got = Fraction(median_of_sorted_arrays_fixed(a, b))
    want = naive_median(a, b)
    if got != want:
        fails += 1
        if fails <= 5:
            print(f"  MISMATCH a={a} b={b} got={got} want={want}")
print(f"  mismatches: {fails} / 5000")
