"""C3: is this memoization decorator correct? Verified by experiment."""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(__file__))


def memoize(fn):
    cache = {}

    def wrapper(*args):
        key = ",".join(str(a) for a in args)
        if key not in cache:
            cache[key] = fn(*args)
        return cache[key]

    wrapper.cache = cache
    return wrapper


def main():
    print("=== Test 1: string-key collision across arg types ===")

    def echo(a, b):
        return (type(a).__name__, type(b).__name__, a, b)

    mf = memoize(echo)
    r1 = mf(1, 2)                       # computes, caches under "1,2"
    r2 = mf("1", "2")                   # key "1,2" collides -> returns cached r1
    print("mf(1, 2)        =", r1)
    print('mf("1", "2")    =', r2)
    print("expected r2 == ('str', 'str', '1', '2'); got", r2)
    print("COLLISION -> wrong result:", r2 != ("str", "str", "1", "2"))

    print()
    print("=== Test 2: single-arg int vs str collision ===")

    def ident(x):
        return (type(x).__name__, x)

    mi = memoize(ident)
    print("mi(5)  =", mi(5))
    print('mi("5")=', mi("5"), "-> collides with mi(5):", mi("5") == mi(5))

    print()
    print("=== Test 3: cached mutable return value is shared / mutable ===")

    def make_list(n):
        return list(range(n))

    ml = memoize(make_list)
    first = ml(3)
    first.append(999)                     # caller mutates the returned list
    second = ml(3)                        # should recompute to [0,1,2]
    print("first  =", first)
    print("second =", second)
    bug_present = second != [0, 1, 2]
    print("CACHED MUTABILITY BUG present (second != [0,1,2]):", bug_present)

    print()
    print("=== Test 4: pure-function happy path works (so the bug is subtle) ===")

    def add(a, b):
        return a + b

    madd = memoize(add)
    print("madd(2, 3) =", madd(2, 3), " madd(2,3) again =", madd(2, 3))
    print("cache size =", len(madd.cache))

    print()
    print("=== Test 5: not thread-safe (concurrent recomputation) ===")
    calls = {"n": 0}
    clock = threading.Lock()

    def slow(x):
        time.sleep(0.01)                  # widen the check-then-store window
        with clock:
            calls["n"] += 1
        return x * x

    ms = memoize(slow)
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()
        ms(7)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print("number of underlying calls for one logical key across 8 threads:",
          calls["n"], "(1 would be required for a correct memo)")


if __name__ == "__main__":
    main()
