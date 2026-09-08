"""I3: verify merge_sorted by brute force against sorted(a + b)."""

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
    random.seed(42)
    failures = 0

    edge_cases = [
        ([], []),
        ([1], []),
        ([], [1]),
        ([1], [1]),
        ([1, 2, 3], [4, 5, 6]),
        ([4, 5, 6], [1, 2, 3]),
        ([1, 1, 1], [1, 1, 1]),
        ([2, 3, 3], [2, 3, 3]),
        ([-10, -5, -1], [-3, -2]),
        (list(range(0, 100, 2)), list(range(1, 100, 2))),
        ([1], list(range(2, 1000))),
        (list(range(1000)), [9999]),
    ]
    for a, b in edge_cases:
        got = merge_sorted(a, b)
        want = sorted(a + b)
        if got != want:
            failures += 1
            print("EDGE FAIL", a[:5], b[:5], got[:10], want[:10])
    print(f"edge cases: {len(edge_cases)} run, {failures} failures")

    trials = 200000
    for _ in range(trials):
        n = random.randint(0, 25)
        m = random.randint(0, 25)
        lo = random.randint(-50, -1)
        hi = random.randint(0, 50)
        a = sorted(random.randint(lo, hi) for _ in range(n))
        b = sorted(random.randint(lo, hi) for _ in range(m))
        got = merge_sorted(a, b)
        want = sorted(a + b)
        if got != want:
            failures += 1
            if failures <= 5:
                print("RANDOM FAIL", a, b, got, want)
            if failures > 20:
                break
    print(f"random trials: {trials} run, {failures} failures total")
    print("VERDICT:", "correct for all tested inputs" if failures == 0 else "INCORRECT")


if __name__ == "__main__":
    main()
