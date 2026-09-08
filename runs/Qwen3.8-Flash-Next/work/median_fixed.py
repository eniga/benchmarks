"""Fixed median of two sorted sequences.

Two things were wrong with the reported implementation once the values are
64-bit record IDs:

* ``float('-inf')`` / ``float('inf')`` sentinels, and
* the even-length averaging ``(<left> + <right>) / 2``, which converts the
  exact half into a float64.

The second one is what produces wrong answers in production: a half-integer
median built from ~2**63-sized IDs is not representable in float64, so the
result is silently rounded. This version never converts an integer to a float:
it selects the needed order statistics with integer comparisons only, and does
the averaging with exact integer arithmetic, returning an ``int`` when the
median is an integer and a :class:`fractions.Fraction` when it is a half.
"""

from fractions import Fraction
from numbers import Integral

__all__ = ["median_of_sorted_arrays"]


def _kth_smallest(a, b, k):
    """Return the k-th (0-based) smallest element of sorted ``a`` and ``b``.

    Runs in O(log(m + n)) with no sentinels and no float comparisons.
    """
    ia, ib = 0, 0
    la, lb = len(a), len(b)
    while True:
        if ia == la:
            return b[ib + k]
        if ib == lb:
            return a[ia + k]
        if k == 0:
            return a[ia] if a[ia] <= b[ib] else b[ib]
        half = (k - 1) // 2
        ja = ia + half
        jb = ib + half
        if ja >= la:
            ja = la - 1
        if jb >= lb:
            jb = lb - 1
        if a[ja] <= b[jb]:
            k -= ja - ia + 1
            ia = ja + 1
        else:
            k -= jb - ib + 1
            ib = jb + 1


def _half_sum(lo, hi):
    """(lo + hi) / 2 without ever converting integers to float."""
    if isinstance(lo, Integral) and isinstance(hi, Integral):
        total = int(lo) + int(hi)
        return total // 2 if total % 2 == 0 else Fraction(total, 2)
    return (lo + hi) / 2


def median_of_sorted_arrays(a, b):
    """Median of two individually-sorted sequences, exactly.

    ``a`` and ``b`` must be sorted non-decreasingly. Returns the element itself
    (an odd total), or the exact average of the two middle elements. Integer
    inputs give an ``int`` or a ``Fraction``; other numeric inputs behave like
    ordinary arithmetic. Raises ``ValueError`` if both inputs are empty.
    """
    n = len(a) + len(b)
    if n == 0:
        raise ValueError("median_of_sorted_arrays: no elements")
    if n % 2:
        return _kth_smallest(a, b, n // 2)
    left = _kth_smallest(a, b, n // 2 - 1)
    right = _kth_smallest(a, b, n // 2)
    return _half_sum(left, right)
