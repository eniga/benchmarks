"""I2: reproduce the 64-bit median bug and show the fix."""

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
    """Same O(log n) binary search, but no data value ever passes through
    float64: sentinels are None and the final average is exact integer
    arithmetic. Returns an int when the median is integral, otherwise an
    exact Fraction (a .5 value above 2**53 is not representable in float64).
    """
    if len(a) > len(b):
        a, b = b, a
    n, m = len(a), len(b)
    if n == 0 and m == 0:
        raise ValueError("at least one array must be non-empty")
    lo, hi = 0, n
    while lo <= hi:
        i = (lo + hi) // 2
        j = (n + m + 1) // 2 - i
        left_a  = a[i-1] if i > 0 else None
        right_a = a[i]   if i < n else None
        left_b  = b[j-1] if j > 0 else None
        right_b = b[j]   if j < m else None
        ok_a = left_a is None or right_b is None or left_a <= right_b
        ok_b = left_b is None or right_a is None or left_b <= right_a
        if ok_a and ok_b:
            max_left = max(x for x in (left_a, left_b) if x is not None)
            if (n + m) % 2:
                return max_left
            min_right = min(x for x in (right_a, right_b) if x is not None)
            total = max_left + min_right
            if total % 2 == 0:
                return total // 2
            return Fraction(total, 2)
        elif left_a is not None and right_b is not None and left_a > right_b:
            hi = i - 1
        else:
            lo = i + 1
    raise AssertionError("unreachable")


if __name__ == "__main__":
    import random

    print("=== Reproduction with the ORIGINAL function ===")
    a = [2**63 - 1]
    b = [2**63]
    got = median_of_sorted_arrays(a, b)
    exact = Fraction((2**63 - 1) + 2**63, 2)
    print(f"a = {a}")
    print(f"b = {b}")
    print(f"original returns: {got!r}  (type {type(got).__name__})")
    print(f"exact median:     {exact}")
    print(f"original correct? {got == exact}")

    a2 = [2**53 + 1]
    b2 = [2**53 + 1]
    got2 = median_of_sorted_arrays(a2, b2)
    print()
    print(f"mechanism: float(2**63 - 1) = {float(2**63 - 1)!r}  (the -1 is lost)")
    print(f"mechanism: float(2**53 + 1) = {float(2**53 + 1)!r}  (the +1 is lost)")
    print()
    print(f"a = {a2}")
    print(f"b = {b2}")
    print(f"original returns: {got2!r}")
    print(f"exact median:     {2**53 + 1}")
    print(f"original correct? {got2 == 2**53 + 1}")

    print()
    print("=== Fixed function on the same inputs ===")
    print(f"fixed(a, b)  = {median_of_sorted_arrays_fixed(a, b)!r}")
    print(f"fixed(a2,b2) = {median_of_sorted_arrays_fixed(a2, b2)!r}")

    print()
    print("=== Fuzz: fixed function vs exact reference (20000 random cases) ===")
    random.seed(7)
    bad = 0
    for _ in range(20000):
        n = random.randint(0, 6)
        m = random.randint(0, 6)
        if random.random() < 0.5:
            pool = list(range(-5, 6))          # small ints (unit-test regime)
        else:
            pool = [random.getrandbits(64) for _ in range(12)]  # 64-bit IDs
        x = sorted(random.choice(pool) for _ in range(n))
        y = sorted(random.choice(pool) for _ in range(m))
        if not x and not y:
            continue
        merged = sorted(x + y)
        k = len(merged)
        expected = merged[k // 2] if k % 2 else Fraction(merged[k // 2 - 1] + merged[k // 2], 2)
        got = median_of_sorted_arrays_fixed(x, y)
        if got != expected:
            bad += 1
            if bad <= 3:
                print("MISMATCH", x, y, got, expected)
    print(f"fuzz mismatches: {bad} / 20000")
