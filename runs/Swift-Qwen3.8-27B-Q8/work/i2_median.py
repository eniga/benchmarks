"""I2: reproduce the 64-bit median bug, then verify the fixed version."""

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
            return Fraction(total, 2)  # exact x.5, no float rounding
        elif left_a > right_b:
            hi = i - 1
        else:
            lo = i + 1


def naive_median(a, b):
    s = sorted(a + b)
    n = len(s)
    if n % 2:
        return s[n // 2]
    return Fraction(s[n // 2 - 1] + s[n // 2], 2)


if __name__ == "__main__":
    # 64-bit record IDs just above the 53-bit float mantissa.
    a = [2**53 + 1]          # 9007199254740993
    b = [2**53 + 2]          # 9007199254740994
    buggy = median_of_sorted_arrays(a, b)
    fixed = median_of_sorted_arrays_fixed(a, b)
    expected = naive_median(a, b)
    print(f"input: a={a}, b={b}")
    print(f"expected median: {expected}")
    print(f"buggy  function: {buggy!r}  -> {'WRONG' if Fraction(buggy) != expected else 'ok'}")
    print(f"fixed  function: {fixed!r}  -> {'WRONG' if fixed != expected else 'ok'}")

    # A second, more production-like pair of 64-bit IDs (integer median).
    a2 = [2**53 + 1]         # 9007199254740993
    b2 = [2**53 + 5]         # 9007199254740997
    print()
    print(f"input: a={a2}, b={b2}")
    print(f"expected median: {naive_median(a2, b2)}")
    print(f"buggy  function: {median_of_sorted_arrays(a2, b2)!r}")
    print(f"fixed  function: {median_of_sorted_arrays_fixed(a2, b2)!r}")

    # Fuzz: fixed version against naive median, small and 64-bit values.
    import random
    random.seed(42)
    bad_fixed = 0
    bad_buggy = 0
    for trial in range(20000):
        n = random.randint(1, 9)
        scale = random.choice([10, 2**53, 2**63])
        a = sorted(random.randint(0, scale) for _ in range(random.randint(0, n)))
        b = sorted(random.randint(0, scale) for _ in range(random.randint(0, n)))
        if not a and not b:
            continue
        expected = naive_median(a, b)
        if Fraction(median_of_sorted_arrays_fixed(a, b)) != expected:
            bad_fixed += 1
            print("MISMATCH fixed", a, b)
        if Fraction(median_of_sorted_arrays(a, b)) != expected:
            bad_buggy += 1
    print()
    print(f"fuzz: 20000 random cases (scales up to 2**63)")
    print(f"  buggy  function mismatches: {bad_buggy}")
    print(f"  fixed  function mismatches: {bad_fixed}")
