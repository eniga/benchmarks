"""C3: probe the two-year-old memoize decorator for correctness."""

def memoize(fn):
    cache = {}
    def wrapper(*args):
        key = ",".join(str(a) for a in args)
        if key not in cache:
            cache[key] = fn(*args)
        return cache[key]
    wrapper.cache = cache
    return wrapper


def f(*args):
    return args


mf = memoize(f)
r1 = mf(1, 2, 3)        # key "1,2,3"
r2 = mf(1, "2,3")       # key "1,2,3" as well -> collision
print(f"mf(1,2,3)  = {r1}")
print(f"mf(1,'2,3') = {r2}   (expected (1, '2,3'))")
print("collision bug:", r2 != (1, "2,3"))

# string args with commas collide too
def g(*parts):
    return parts

mg = memoize(g)
print("g('a','b','c') =", mg("a", "b", "c"))
print("g('a,b','c')   =", mg("a,b", "c"), "  (expected ('a,b','c'))")

# kwargs are dropped: same key for different calls
def h(a, b=0):
    return (a, b)

mh = memoize(h)
print("h(1)      =", mh(1))
print("h(1, b=5) ->", end=" ")
try:
    print(mh(1, b=5))
except TypeError as e:
    print("TypeError:", e)

# thread safety: concurrent misses compute the body multiple times
import threading
calls = []
barrier = threading.Barrier(8)
def slow(x):
    barrier.wait()      # all 8 threads reach the miss together
    calls.append(1)
    time.sleep(0.05)    # hold the miss open so the others overlap it
    return x

import time
ms = memoize(slow)
ts = [threading.Thread(target=ms, args=(7,)) for _ in range(8)]
[t.start() for t in ts]
[t.join() for t in ts]
print(f"8 threads, same key: body executed {len(calls)} times (race, no locking)")
