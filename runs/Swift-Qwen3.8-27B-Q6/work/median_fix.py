"""I2: reproduce the 64-bit ID median bug, then verify the fix."""

from fractions import Fraction


def median_of_sorted_arrays_buggy(a, b):
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


def median_of_sorted_arrays(a, b):
    """Fixed: never routes 64-bit values through float arithmetic.

    Sentinels are None (compared explicitly) and the even-count median is
    computed with exact integer arithmetic, returned as a Fraction so that
    values of the form x.5 stay exact for arbitrarily large IDs.
    """
    if len(a) > len(b):
        a, b = b, a
    lo, hi = 0, len(a)
    while lo <= hi:
        i = (lo + hi) // 2
        j = (len(a) + len(b) + 1) // 2 - i
        left_a  = a[i-1] if i > 0 else None
        right_a = a[i]   if i < len(a) else None
        left_b  = b[j-1] if j > 0 else None
        right_b = b[j]   if j < len(b) else None
        ok_a = left_a is None or right_b is None or left_a <= right_b
        ok_b = left_b is None or right_a is None or left_b <= right_a
        if ok_a and ok_b:
            if (len(a) + len(b)) % 2:
                # max of the two left sides; at least one is a real element
                if left_a is None:
                    return left_b
                if left_b is None:
                    return left_a
                return left_a if left_a >= left_b else left_b
            # even total: both boundary values are real elements
            x = left_a if left_a is not None and (left_b is None or left_a >= left_b) else left_b
            y = right_b if right_b is not None and (right_a is None or right_b <= right_a) else right_a
            return Fraction(x + y, 2)
        elif left_a is not None and right_b is not None and left_a > right_b:
            hi = i - 1
        else:
            lo = i + 1


def main() -> None:
    # --- Reproduction input: 64-bit record IDs, even total count ----------
    a = [2**60 + 1]
    b = [2**60 + 2]
    expected = Fraction(2**60 + 1 + 2**60 + 2, 2)  # 2305843009213693953.5
    buggy = median_of_sorted_arrays_buggy(a, b)
    fixed = median_of_sorted_arrays(a, b)
    print("input a =", a)
    print("input b =", b)
    print("true median      =", expected)
    print("buggy result     =", buggy, "(type:", type(buggy).__name__ + ")")
    print("fixed result     =", fixed, "(type:", type(fixed).__name__ + ")")
    print("buggy exact value =", Fraction(buggy), "(value the float actually holds)")
    print("buggy == true?   ", Fraction(buggy) == expected)
    print("fixed == true?   ", fixed == expected)

    # A second case: large IDs, odd total count (odd case was already exact).
    a2 = [2**62, 2**62 + 10]
    b2 = [2**62 + 5]
    print()
    print("odd-count case: buggy =", median_of_sorted_arrays_buggy(a2, b2),
          " fixed =", median_of_sorted_arrays(a2, b2))

    # --- Differential check of the fix against a naive exact median -------
    import random
    random.seed(42)
    for trial in range(200_000):
        n = random.randint(0, 6)
        m = random.randint(0, 6)
        hi = random.choice([10, 2**64 - 1])
        aa = sorted(random.randint(0, hi) for _ in range(n))
        bb = sorted(random.randint(0, hi) for _ in range(m))
        if not aa and not bb:
            continue
        merged = sorted(aa + bb)
        k = len(merged)
        true_med = merged[k // 2] if k % 2 else Fraction(merged[k // 2 - 1] + merged[k // 2], 2)
        got = median_of_sorted_arrays(aa, bb)
        assert got == true_med, (aa, bb, got, true_med)
    print()
    print("differential check: 200000 random cases passed")


if __name__ == "__main__":
    main()
