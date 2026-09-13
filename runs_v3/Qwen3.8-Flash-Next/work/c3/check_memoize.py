"""Task C3 - verification of the two-year-old memoize decorator.

Each property is checked against the decorator as found and against the
corrected one in memoize_as_found.py, so the report says which version fails
what.
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


def check(label, got, expected):
    ok = got == expected
    print(f"  {label:<50} {'ok  ' if ok else 'FAIL'} got={got!r} expected={expected!r}")


# --------------------------------------------------------------------------
section("1. different argument lists share one cache slot (string key)")


def describe(a, b):
    return f"{type(a).__name__}:{a}|{type(b).__name__}:{b}"


for name, dec in (("as found", memoize), ("fixed", memoize_fixed)):
    f = dec(describe)
    f(1, 2)                                   # key ",": str(1)+","+str(2) == "1,2"
    check(f"{name}: f(1,2) then f('1','2')", f("1", "2"), describe("1", "2"))

    g = dec(lambda *a: len(a))
    g(1, 2)                                   # key "1,2"
    check(f"{name}: f(1,2) then f('1,2') (arity)", g("1,2"), 1)

    h = dec(lambda *a: "+".join(str(x) for x in a))
    h(1, 2, 3)                                # key "1,2,3"
    check(f"{name}: f(1,2,3) then f(1,'2,3')", h(1, "2,3"), "1+2,3")


# --------------------------------------------------------------------------
section("2. distinct objects that stringify the same collide")


class Ticket:
    def __init__(self, tid, fee):
        self.tid, self.fee = tid, fee

    def __str__(self):                      # what many __str__ implementations do
        return f"ticket {self.tid}"


for name, dec in (("as found", memoize), ("fixed", memoize_fixed)):
    f = dec(lambda t: t.fee)
    t1, t2 = Ticket("A1", 10), Ticket("A1", 20)          # different objects, same str()
    first = f(t1)
    check(f"{name}: fee(ticket A1 #1) then fee(ticket A1 #2)", (first, f(t2)), (10, 20))

# checked as well, and it does NOT fail on this machine: str() of a mutated
# argument usually reflects the mutation, so the stale-key worry does not bite
# for a plain list argument.
for name, dec in (("as found", memoize), ("fixed", memoize_fixed)):
    f = dec(lambda xs: sum(xs))
    xs = [1]
    first = f(xs)
    xs.append(2)
    check(f"{name}: (control) total([1]) then total([1,2])", (first, f(xs)), (1, 3))


# --------------------------------------------------------------------------
section("3. keyword arguments and function metadata")


def volume(a, b=10, c=1):
    """Return the box volume."""
    return a * b * c


for name, dec in (("as found", memoize), ("fixed", memoize_fixed)):
    f = dec(volume)
    try:
        got = f(2, b=5)
    except TypeError as exc:
        got = f"TypeError: {exc}"
    check(f"{name}: f(2, b=5)", got, 10)

for name, dec in (("as found", memoize), ("fixed", memoize_fixed)):
    f = dec(volume)
    check(f"{name}: __name__/__doc__ preserved",
          (f.__name__, f.__doc__), ("volume", "Return the box volume."))


# --------------------------------------------------------------------------
section("4. concurrent first calls on one key")

N_THREADS = 16


def timed_run(dec_label, decorator):
    state = {"runs": 0}
    lock = threading.Lock()

    def slow_add(a, b):
        with lock:
            state["runs"] += 1
        time.sleep(0.05)                 # widen the window; the wrapped fn has
        return a + b                     # side effects (the counter) here

    f = decorator(slow_add)
    threads = [threading.Thread(target=f, args=(1, 2)) for _ in range(N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    runs = state["runs"]
    print(f"  {dec_label:<34} wrapped fn executed {runs:>2}/{N_THREADS} times "
          f"for a single key ({'ok' if runs == 1 else 'NOT ok - duplicated work/side effects'})")


timed_run("as found", memoize)
timed_run("fixed (thread_safe=False)", memoize_fixed)
timed_run("fixed (thread_safe=True)", lambda fn: memoize_fixed(fn, thread_safe=True))


# --------------------------------------------------------------------------
section("5. cache growth")
for name, build in (("as found", lambda: memoize(lambda i: i * 2)),
                    ("fixed(maxsize=128)", lambda: memoize_fixed(lambda i: i * 2, maxsize=128))):
    f = build()
    for i in range(5000):
        f(i)
    print(f"  {name:<22} cache entries after 5000 distinct calls: {len(f.cache)}")


# --------------------------------------------------------------------------
section("6. what it does get right")


def fib_pair(dec):
    @dec
    def fib(n):
        if n < 2:
            return n
        return fib(n - 1) + fib(n - 2)
    return fib


print(f"  recursion through the wrapper works: memoize fib(30)   = {fib_pair(memoize)(30)}")
print(f"                                    fixed    fib(30)   = {fib_pair(memoize_fixed)(30)}")
print(f"  correct results for hashable, immutable, positional args: see case 1 first calls")
print(f"  repeated identical calls are served from the cache (one execution per key): "
      f"see case 4, single-threaded")
print(f"  None/False-y return values are cached correctly, because the code tests "
      f"'key not in cache' rather than truthiness")


def falsy_probe():
    calls = {"n": 0}

    @memoize
    def f(x):
        calls["n"] += 1
        return None if x == 0 else False
    f(0); f(0); f(1); f(1)
    print(f"  falsy returns cached: calls={calls['n']} (expected 2)")


falsy_probe()

print()
print("verdict: the decorator as found is NOT correct.")
