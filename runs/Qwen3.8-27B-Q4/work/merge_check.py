"""Verify merge_sorted for all inputs via exhaustive small cases + randomization."""

import itertools
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


def check(a, b, label):
    got = merge_sorted(a, b)
    want = sorted(a + b)
    if got != want:
        print(f"  FAIL [{label}]: a={a} b={b} got={got} want={want}")
        return False
    # sortedness of the result itself
    if any(got[k] > got[k + 1] for k in range(len(got) - 1)):
        print(f"  FAIL [not sorted] a={a} b={b} got={got}")
        return False
    return True


print("=== 1. Exhaustive: all value combinations over {0, 1, 2}, lengths 0..3 ===")
fails = 0
total = 0
values = [0, 1, 2]
# merge_sorted requires sorted inputs: enumerate all non-decreasing
# sequences (combinations with replacement) over {0,1,2} of length 0..3.
for la in range(4):
    for lb in range(4):
        for a in itertools.combinations_with_replacement(values, la):
            for b in itertools.combinations_with_replacement(values, lb):
                total += 1
                if not check(list(a), list(b), "exhaustive"):
                    fails += 1
print(f"  cases: {total}, failures: {fails}")

print("=== 2. Randomized: 200000 random sorted lists ===")
random.seed(7)
fails = 0
for trial in range(200_000):
    n = random.randint(0, 30)
    m = random.randint(0, 30)
    lo = random.choice([-10**18, -100, -1, 0])
    hi = random.choice([1, 100, 10**18])
    a = sorted(random.randint(lo, hi) for _ in range(n))
    b = sorted(random.randint(lo, hi) for _ in range(m))
    if not check(a, b, "random"):
        fails += 1
        if fails > 5:
            break
print(f"  cases: 200000, failures: {fails}")

print("=== 3. Edge cases ===")
edges = [
    ([], []),
    ([], [1, 2, 3]),
    ([1, 2, 3], []),
    ([1], [1]),
    ([5, 5, 5], [5, 5]),
    ([-5, -1], [-3, 0]),
    ([10**18], [10**18 + 1]),
]
for a, b in edges:
    ok = check(a, b, "edge")
    print(f"  a={a} b={b} -> {merge_sorted(a, b)}  ok={ok}")

print("=== 4. Stability check (equal elements taken from a first) ===")
# Tagged simulation: a elements are (v, 'a'), b elements (v, 'b');
# merge on value must prefer a on ties, i.e. result of values must match
# merge of tagged lists sorted by (value, source) with 'a' < 'b'.
random.seed(11)
stable_ok = True
for trial in range(20_000):
    a = sorted(random.randint(0, 5) for _ in range(random.randint(0, 8)))
    b = sorted(random.randint(0, 5) for _ in range(random.randint(0, 8)))
    got = merge_sorted(a, b)
    tagged = sorted([(v, 0) for v in a] + [(v, 1) for v in b])
    want = [v for v, _ in tagged]
    if got != want:
        stable_ok = False
        print(f"  STABILITY FAIL a={a} b={b} got={got} want={want}")
        break
print(f"  stability ok: {stable_ok}")
