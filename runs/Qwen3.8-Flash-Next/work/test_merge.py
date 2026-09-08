"""Verification of merge_sorted: exhaustive, randomized and property-based."""

import copy
import itertools
import random
import unittest
from collections import Counter


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


def all_sorted_lists(pool, max_len):
    for length in range(max_len + 1):
        for combo in itertools.combinations_with_replacement(pool, length):
            yield list(combo)


class MergeTests(unittest.TestCase):
    def test_exhaustive_over_small_multisets(self):
        pool = [0, 1, 2, 3]
        cases = 0
        for a in all_sorted_lists(pool, 4):
            for b in all_sorted_lists(pool, 4):
                out = merge_sorted(a, b)
                self.assertEqual(out, sorted(a + b), f"a={a} b={b} out={out}")
                cases += 1
        self.assertEqual(cases, 70 * 70)  # C(4+n-1, n) summed over n=0..4 = 70

    def test_duplicates_across_both_inputs(self):
        a = [1, 1, 1, 2, 2, 5]
        b = [1, 1, 3, 3, 5, 5, 5]
        self.assertEqual(merge_sorted(a, b), sorted(a + b))

    def test_empty_sides(self):
        self.assertEqual(merge_sorted([], []), [])
        self.assertEqual(merge_sorted([], [1, 2, 3]), [1, 2, 3])
        self.assertEqual(merge_sorted([1, 2, 3], []), [1, 2, 3])

    def test_disjoint_ranges(self):
        a = list(range(0, 10))
        b = list(range(10, 20))
        self.assertEqual(merge_sorted(a, b), list(range(20)))
        self.assertEqual(merge_sorted(b, a), list(range(20)))

    def test_one_exhausted_first(self):
        a = [1, 100, 200]
        b = [2, 3, 4, 5]
        self.assertEqual(merge_sorted(a, b), [1, 2, 3, 4, 5, 100, 200])

    def test_negative_and_float_values(self):
        a = [-10.5, -2.0, 0.0, 4.25]
        b = [-10.4, -1.0, 4.2]
        self.assertEqual(merge_sorted(a, b), sorted(a + b))

    def test_non_numeric_comparable_types(self):
        a = ["apple", "banana", "pear"]
        b = ["apricot", "cherry", "pear", "zebra"]
        self.assertEqual(merge_sorted(a, b), sorted(a + b))

    def test_inputs_are_not_mutated_and_result_is_new(self):
        a = [1, 3, 5]
        b = [2, 4]
        a_before, b_before = copy.deepcopy(a), copy.deepcopy(b)
        out = merge_sorted(a, b)
        self.assertEqual(a, a_before)
        self.assertEqual(b, b_before)
        self.assertIsNot(out, a)
        self.assertIsNot(out, b)

    def test_same_object_twice(self):
        a = [1, 2, 3]
        self.assertEqual(merge_sorted(a, a), [1, 1, 2, 2, 3, 3])
        self.assertEqual(a, [1, 2, 3])

    def test_stability_ties_come_from_a_first(self):
        class Rec:
            def __init__(self, key, src):
                self.key, self.src = key, src

            def __le__(self, other):
                return self.key <= other.key

            def __repr__(self):
                return f"{self.key}/{self.src}"

        a = [Rec(1, "a"), Rec(1, "a"), Rec(2, "a")]
        b = [Rec(1, "b"), Rec(1, "b"), Rec(2, "b")]
        out = merge_sorted(a, b)
        self.assertEqual([r.src for r in out], ["a", "a", "b", "b", "a", "b"])

    def test_randomized(self):
        rng = random.Random(12345)
        for trial in range(20000):
            n = rng.randint(0, 60)
            m = rng.randint(0, 60)
            a = sorted(rng.randint(-100, 100) for _ in range(n))
            b = sorted(rng.randint(-100, 100) for _ in range(m))
            out = merge_sorted(a, b)
            self.assertEqual(out, sorted(a + b), f"trial {trial} a={a} b={b}")
            self.assertEqual(len(out), n + m)
            self.assertEqual(Counter(out), Counter(a) + Counter(b))

    def test_large_inputs(self):
        rng = random.Random(9)
        a = sorted(rng.randint(0, 10**9) for _ in range(100_000))
        b = sorted(rng.randint(0, 10**9) for _ in range(100_000))
        out = merge_sorted(a, b)
        self.assertEqual(out, sorted(a + b))
        self.assertEqual(len(out), 200_000)

    def test_termination_bound(self):
        # The loop appends exactly one element per iteration and can run at
        # most len(a) + len(b) iterations; check the counter arithmetic.
        rng = random.Random(5)
        a = sorted(rng.randint(0, 5) for _ in range(500))
        b = sorted(rng.randint(0, 5) for _ in range(500))
        out = merge_sorted(a, b)
        self.assertEqual(len(out), len(a) + len(b))
        self.assertEqual(a[0] if a else None, min(out))


if __name__ == "__main__":
    unittest.main(verbosity=2)
