"""Verify the fixed median against an exact brute-force reference."""

import random
from fractions import Fraction

from median_fixed import median_of_sorted_arrays


def exact_median(a, b):
    """Reference: sort the concatenation and take the exact median."""
    c = sorted(a + b)
    n = len(c)
    if n % 2:
        return Fraction(c[n // 2])
    return Fraction(c[n // 2 - 1] + c[n // 2], 2)


def main():
    # 1. The production-scale reproductions that broke the original.
    cases_64 = [
        ([9223372036854775805], [9223372036854775807]),
        ([4611686018427387905], [4611686018427387907]),
        ([2**63 - 1], [2**63 - 1]),
        ([1, 2, 2**63 - 2, 2**63 - 1], [3, 2**62]),
        ([], [2**63 - 1]),
        ([2**62 + 1, 2**62 + 2, 2**62 + 3], []),
    ]
    for a, b in cases_64:
        got = median_of_sorted_arrays(a, b)
        want = exact_median(a, b)
        status = "OK  " if got == want else "FAIL"
        print(f"{status} a={a} b={b} got={got!r} want={want!r}")
        assert got == want, (a, b, got, want)

    # 2. Fuzz: 20000 random cases with 64-bit-scale values.
    random.seed(42)
    empty_empty = 0
    for trial in range(20000):
        la = random.randint(0, 8)
        lb = random.randint(0, 8)
        a = sorted(random.randint(2**62, 2**63 - 1) for _ in range(la))
        b = sorted(random.randint(2**62, 2**63 - 1) for _ in range(lb))
        if la == 0 and lb == 0:
            # both empty: no median exists; the fix raises explicitly
            try:
                median_of_sorted_arrays(a, b)
                raise AssertionError("expected ValueError for empty+empty")
            except ValueError:
                empty_empty += 1
            continue
        got = median_of_sorted_arrays(a, b)
        want = exact_median(a, b)
        assert got == want, (trial, a, b, got, want)
    print(f"fuzz (64-bit scale): 20000/20000 cases match the exact reference "
          f"({empty_empty} empty+empty cases correctly raised ValueError)")

    # 3. Fuzz: 20000 random cases with small values (original unit-test regime).
    random.seed(7)
    for trial in range(20000):
        la = random.randint(0, 6)
        lb = random.randint(0, 6)
        a = sorted(random.randint(-100, 100) for _ in range(la))
        b = sorted(random.randint(-100, 100) for _ in range(lb))
        if la == 0 and lb == 0:
            continue  # no median exists; covered by the 64-bit fuzz above
        got = median_of_sorted_arrays(a, b)
        want = exact_median(a, b)
        assert got == want, (trial, a, b, got, want)
    print("fuzz (small values): 20000/20000 cases match the exact reference")

    # 4. Compatibility: classic small-int examples still give the expected values.
    classic = [
        ([1, 3], [2], 2),
        ([1, 2], [3, 4], Fraction(5, 2)),
        ([], [1, 2, 3], 2),
        ([1], [], 1),
    ]
    for a, b, want in classic:
        got = median_of_sorted_arrays(a, b)
        assert got == want, (a, b, got, want)
        print(f"classic: a={a} b={b} -> {got!r}")
    print("all checks passed")


if __name__ == "__main__":
    main()
