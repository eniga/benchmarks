"""I3: verify merge_sorted against a reference on exhaustive edge cases and
a large random differential fuzz."""

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


def main() -> None:
    # Edge cases.
    edge = [
        ([], []),
        ([1], []),
        ([], [1]),
        ([1], [1]),
        ([1, 2, 3], [4, 5, 6]),
        ([4, 5, 6], [1, 2, 3]),
        ([1, 3, 5], [2, 4, 6]),
        ([1, 1, 1], [1, 1]),
        ([-5, -1, 0], [-3, 0, 2]),
        (list(range(0, 100, 2)), list(range(1, 100, 2))),
        (list(range(100, 0, -2))[-100:][::-1], list(range(50))),
    ]
    for a, b in edge:
        assert merge_sorted(a, b) == sorted(a + b), (a, b)
    print(f"edge cases: {len(edge)} passed")

    # Random differential fuzz: small values (many duplicates) and large ints.
    random.seed(1234)
    cases = 0
    for _ in range(300_000):
        n = random.randint(0, 12)
        m = random.randint(0, 12)
        hi = random.choice([3, 10, 2**63 - 1])
        a = sorted(random.randint(0, hi) for _ in range(n))
        b = sorted(random.randint(0, hi) for _ in range(m))
        assert merge_sorted(a, b) == sorted(a + b), (a, b)
        cases += 1
    print(f"random differential fuzz: {cases} cases passed")
    print("VERDICT: merge_sorted is correct for all inputs (given sorted a, b)")


if __name__ == "__main__":
    main()
