"""Verify merge_sorted against sorted(a+b) on exhaustive edge cases,
randomized trials, and a stability check for equal keys."""

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


# --- edge cases ---------------------------------------------------------
edge_cases = [
    ([], []),
    ([1], []),
    ([], [1]),
    ([1], [1]),
    ([1, 3, 5], [2, 4, 6]),
    ([2, 4, 6], [1, 3, 5]),
    ([1, 1, 1, 1], [1, 1]),
    (list(range(0, 100, 2)), list(range(1, 100, 2))),
    (sorted(range(99, -1, -2)), [0]),
    ([-5, -5, 0], [-5, 3, 3, 3]),
]
for a, b in edge_cases:
    got = merge_sorted(a, b)
    want = sorted(a + b)
    assert got == want, (a, b, got, want)
print(f"edge cases passed: {len(edge_cases)}")

# --- randomized trials (heavy duplicates) --------------------------------
random.seed(7)
for _ in range(20000):
    la = random.randint(0, 40)
    lb = random.randint(0, 40)
    a = sorted(random.randint(-10, 10) for _ in range(la))
    b = sorted(random.randint(-10, 10) for _ in range(lb))
    got = merge_sorted(a, b)
    want = sorted(a + b)
    assert got == want, (a, b, got, want)
print("randomized trials passed: 20000")

# --- stability: equal keys must keep a's elements before b's ------------
class V:
    __slots__ = ("v", "src")

    def __init__(self, v, src):
        self.v, self.src = v, src

    def __le__(self, other):
        return self.v <= other.v

    def __lt__(self, other):
        return self.v < other.v

    def __eq__(self, other):
        return self.v == other.v

    def __repr__(self):
        return f"V({self.v},{self.src})"


random.seed(11)
for _ in range(5000):
    la = random.randint(0, 20)
    lb = random.randint(0, 20)
    a = [V(random.randint(0, 5), "a") for _ in range(la)]
    b = [V(random.randint(0, 5), "b") for _ in range(lb)]
    a.sort(key=lambda x: x.v)
    b.sort(key=lambda x: x.v)
    got = merge_sorted(a, b)
    assert [x.v for x in got] == sorted([x.v for x in a + b])
    # stability: for each value, all 'a' copies must precede all 'b' copies
    for val in range(6):
        srcs = [x.src for x in got if x.v == val]
        assert srcs == sorted(srcs), (a, b, got)  # 'a' < 'b' lexicographically
print("stability trials passed: 5000")

print("ALL CHECKS PASSED")
