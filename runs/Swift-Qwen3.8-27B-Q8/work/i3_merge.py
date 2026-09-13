"""I3: brute-force verification of merge_sorted against sorted(a+b)."""

import random


def merge_sorted(a, b):
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


def main():
    # Exhaustive small cases: all sorted multisets of size <= 4 over {0,1,2}.
    from itertools import combinations_with_replacement
    exhaustive = 0
    for la in range(5):
        for lb in range(5):
            for va in combinations_with_replacement(range(3), la):
                for vb in combinations_with_replacement(range(3), lb):
                    a, b = list(va), list(vb)
                    assert merge_sorted(a, b) == sorted(a + b), (a, b)
                    exhaustive += 1
    print(f"exhaustive small cases: {exhaustive} ok")

    # Random fuzz: sorted lists with duplicates, empty lists, one-sided.
    random.seed(7)
    for trial in range(200000):
        n = random.randint(0, 30)
        m = random.randint(0, 30)
        a = sorted(random.randint(0, 50) for _ in range(n))
        b = sorted(random.randint(0, 50) for _ in range(m))
        got = merge_sorted(a, b)
        want = sorted(a + b)
        assert got == want, (a, b)
    print("random fuzz: 200000 cases ok")

    # Edge cases spelled out.
    assert merge_sorted([], []) == []
    assert merge_sorted([], [1, 2]) == [1, 2]
    assert merge_sorted([3, 4], []) == [3, 4]
    assert merge_sorted([1, 1, 1], [1, 1]) == [1, 1, 1, 1, 1]
    assert merge_sorted([1, 3], [2, 4]) == [1, 2, 3, 4]
    # Stability: on ties, elements from a come first (a's 2 before b's 2).
    print("edge cases ok")


if __name__ == "__main__":
    main()
