"""Fixed median of two sorted arrays.

Root cause of the original bug
------------------------------
The binary search itself is correct: Python compares int and float
exactly, so the float('-inf')/float('inf') sentinels do not corrupt the
search. The bug is the final line for even-length input:

    return (max(left_a, left_b) + min(right_a, right_b)) / 2

``/`` is true division, which converts its operands to float64. A float64
has a 53-bit mantissa, but 64-bit record IDs use up to 63 bits, so the
conversion rounds. Python's integer addition ``a + b`` is exact
(arbitrary precision), but the immediately following ``/ 2`` then rounds
the exact integer sum to the nearest representable float64 -- losing up to
2**11 = 2048 at the 2**63 scale. Small values in the unit tests fit in 53
bits, which is why every unit test passed.

The fix performs no float arithmetic on the data at all:
* the sentinels are ``None`` (comparisons handle the boundaries explicitly);
* the odd-length case returns the actual element, unchanged;
* the even-length case adds the two middle values as exact integers and
  divides by 2 with integer arithmetic, returning an ``int`` when the
  median is an integer and a ``Fraction`` (an exact half-integer) when it
  is not. A half-integer such as 9223372036854775805.5 cannot be
  represented exactly in any float64, so an exact rational is the only
  correct return type for that case.
"""

from fractions import Fraction


def median_of_sorted_arrays(a, b):
    """Exact median of two sorted arrays.

    Returns an int when the median is an integer, otherwise a Fraction
    (a half-integer). Works for arbitrarily large integers. Raises
    ValueError if both arrays are empty.
    """
    if not a and not b:
        raise ValueError("both arrays are empty; no median exists")
    if len(a) > len(b):
        a, b = b, a
    n = len(a) + len(b)
    lo, hi = 0, len(a)
    while lo <= hi:
        i = (lo + hi) // 2
        j = (n + 1) // 2 - i
        left_a = a[i - 1] if i > 0 else None
        right_a = a[i] if i < len(a) else None
        left_b = b[j - 1] if j > 0 else None
        right_b = b[j] if j < len(b) else None
        if (left_a is None or right_b is None or left_a <= right_b) and \
           (left_b is None or right_a is None or left_b <= right_a):
            if n % 2:
                return max(x for x in (left_a, left_b) if x is not None)
            lo_mid = max(x for x in (left_a, left_b) if x is not None)
            hi_mid = min(x for x in (right_a, right_b) if x is not None)
            total = lo_mid + hi_mid
            if total % 2 == 0:
                return total // 2
            return Fraction(total, 2)
        elif left_a is not None and right_b is not None and left_a > right_b:
            hi = i - 1
        else:
            lo = i + 1
    raise AssertionError("unreachable")
