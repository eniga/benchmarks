"""Task C3 - verification of the two-year-old memoize decorator.

Every case below is run against the decorator as found and against the
corrected one, so the report says which failures belong to which version.
"""

from __future__ import annotations

import threading
import time

from memoize_as_found import memoize, memoize_fixed


def section(title):
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


class Report:
    def __init__(self):
        self.rows = []

    def add(self, case, version, outcome, detail=""):
        self.rows.append((case, version, outcome, detail))
        print(f"  {case:<44} {version:<14} {outcome:<10} {detail}")


rep = Report()


def probe_signature(case, make, expected_first, expected_second, a1, a2, kwargs=False):
    """Call twice with arguments that must not share a cache slot."""
    fn = make(lambda a, b=None: f"first({a!r},{b!r})" if b is None else f"second({a!r},{b!r})")
    try:
        if kwargs:
            first = fn(1, b=2)
            second = fn(1, 2)
        else:
            first = fn(*a1)
            second = fn(*a2)
    except TypeError as exc:
        rep.add(case, make_label[0], "TypeError", str(exc))
        return
    ok_first = first == expected_first
    ok_second = second == expected_second
    rep.add(case, make_label[0],
            "correct" if (ok_first and ok_second) else "WRONG RESULT",
            f"{first!r} then {second!r}"
            + ("" if ok_second else f"   expected {expected_second!r}"))


def as_found(fn):
    return memoize(fn)


def as_fixed(fn):
    return memoize_fixed(fn)


# --------------------------------------------------------------------------
section("1. the string key merges different argument lists")
make_label = ["as found"]
probe_signature("f(1,2) then f('1','2')", as_found,
                "first(1,None)", "second('1','2')" if False else 'first(None)', (1, 2), (1, 2))
# the above is only a scaffold; the real probes follow
