"""Tests for the fixed median_of_sorted_arrays, plus the original-vs-fixed
differential comparison. Stdlib unittest only.
"""

import copy
import itertools
import random
import unittest
from fractions import Fraction

from median_fixed import median_of_sorted_arrays
from median_repro import exact_median, median_of_sorted_arrays as median_original


def check(a, b):
    """Assert the implementation agrees with the exact reference."""
    a_copy, b_copy = copy.deepcopy(a), copy.deepcopy(b)
    got = median_of_sorted_arrays(list(a), list(b))
    want = exact_median(a, b)
    assert got == want, f"a={a} b={b} got={got!r} want={want!r}"
    assert a == a_copy and b == b_copy, "inputs were mutated"


class ExactnessTests(unittest.TestCase):
    def test_exhaustive_small_multisets(self):
        values = range(-2, 3)
        cases = 0
        for na in range(0, 4):
            for nb in range(0, 4):
                if na + nb == 0:
                    continue
                for ca in itertools.combinations_with_replacement(values, na):
                    for cb in itertools.combinations_with_replacement(values, nb):
                        a = sorted(ca)
                        b = sorted(cb)
                        check(a, b)
                        cases += 1
        self.assertEqual(cases, 56 * 56 - 1)

    def test_random_64_bit_ids(self):
        rng = random.Random(20240908)
        for _ in range(20000):
            na = rng.randint(0, 20)
            nb = rng.randint(0, 20)
            if na + nb == 0:
                nb = 1
            a = sorted(rng.randint(2**63 - 10**13, 2**63 - 1) for _ in range(na))
            b = sorted(rng.randint(2**63 - 10**13, 2**63 - 1) for _ in range(nb))
            check(a, b)

    def test_random_negative_and_mixed(self):
        rng = random.Random(7)
        for _ in range(20000):
            na = rng.randint(0, 15)
            nb = rng.randint(0, 15)
            if na + nb == 0:
                na = 1
            a = sorted(rng.randint(-(2**62), 2**62) for _ in range(na))
            b = sorted(rng.randint(-(2**62), 2**62) for _ in range(nb))
            check(a, b)

    def test_beyond_64_bit(self):
        huge = Fraction(2) ** 200
        self.assertEqual(median_of_sorted_arrays([2**200, 2**200 + 1], [2**200 + 3, 2**200 + 100]),
                         2**200 + 2)
        self.assertEqual(median_of_sorted_arrays([2**200], [2**200 + 1]),
                         huge + Fraction(1, 2))

    def test_doubles_untouched_by_float(self):
        got = median_of_sorted_arrays([1.0, 2.0], [3.0])
        self.assertEqual(got, 2.0)
        self.assertIsInstance(got, float)


class BehaviourTests(unittest.TestCase):
    def test_odd_count_returns_the_element_itself(self):
        self.assertEqual(median_of_sorted_arrays([1], [2, 3]), 2)
        self.assertIsInstance(median_of_sorted_arrays([1], [2, 3]), int)

    def test_even_count_integer_average(self):
        self.assertEqual(median_of_sorted_arrays([1, 2], [3, 4]), Fraction(5, 2))
        self.assertEqual(median_of_sorted_arrays([1, 3], [5, 7]), 4)
        self.assertIsInstance(median_of_sorted_arrays([1, 3], [5, 7]), int)

    def test_empty_and_one_sided(self):
        self.assertEqual(median_of_sorted_arrays([], [7]), 7)
        self.assertEqual(median_of_sorted_arrays([1, 2, 3], []), 2)
        with self.assertRaises(ValueError):
            median_of_sorted_arrays([], [])

    def test_duplicates_and_same_list(self):
        self.assertEqual(median_of_sorted_arrays([5, 5, 5], [5, 5]), 5)
        self.assertEqual(median_of_sorted_arrays([1, 1], [1, 1]), 1)

    def test_inputs_not_mutated(self):
        a = [1, 3, 5]
        b = [2, 4, 6]
        median_of_sorted_arrays(a, b)
        self.assertEqual(a, [1, 3, 5])
        self.assertEqual(b, [2, 4, 6])

    def test_repro_from_the_report_is_now_exact(self):
        a = [9223371320496496436, 9223371371131448672, 9223371481323450853,
             9223371500239844994, 9223371599347164410, 9223371899792021427]
        b = [9223371315166090657, 9223371346690597146, 9223371376788386601,
             9223371564997455239, 9223371591843761369, 9223371678342713263,
             9223371715866903588, 9223371836142878188, 9223371866383667503,
             9223371928941697825, 9223372025013975218, 9223372027282403590]
        got = median_of_sorted_arrays(a, b)
        self.assertEqual(got, Fraction(18446743191190925779, 2))
        self.assertNotEqual(median_original(list(a), list(b)), got)

    def test_large_arrays_are_fast_and_exact(self):
        import time
        rng = random.Random(11)
        a = sorted(rng.randint(0, 2**63) for _ in range(1_000_000))
        b = sorted(rng.randint(0, 2**63) for _ in range(1_000_000))
        start = time.monotonic()
        got = median_of_sorted_arrays(a, b)
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 0.05)          # O(log n): microseconds, not a merge
        want = exact_median(a, b)               # full merge as the reference
        self.assertEqual(got, want)
        print(f"        large-array median took {elapsed * 1e6:.1f} us")


class DifferentialTests(unittest.TestCase):
    def test_original_is_wrong_only_in_the_large_value_range(self):
        rng = random.Random(3)
        small_bad = 0
        large_bad = 0
        for _ in range(5000):
            a = sorted(rng.randint(0, 50) for _ in range(rng.randint(1, 12)))
            b = sorted(rng.randint(0, 50) for _ in range(rng.randint(0, 12)))
            if median_of_sorted_arrays(list(a), list(b)) != median_original(list(a), list(b)):
                small_bad += 1
        for _ in range(5000):
            a = sorted(rng.randint(2**63 - 10**12, 2**63 - 1) for _ in range(rng.randint(1, 12)))
            b = sorted(rng.randint(2**63 - 10**12, 2**63 - 1) for _ in range(rng.randint(0, 12)))
            if median_of_sorted_arrays(list(a), list(b)) != median_original(list(a), list(b)):
                large_bad += 1
        self.assertEqual(small_bad, 0)
        self.assertGreater(large_bad, 1000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
