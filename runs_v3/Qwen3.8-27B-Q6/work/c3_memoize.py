"""C3: verify the memoize decorator and state whether it is correct."""

import sys


def memoize(fn):
    cache = {}
    def wrapper(*args):
        key = ",".join(str(a) for a in args)
        if key not in cache:
            cache[key] = fn(*args)
        return cache[key]
    wrapper.cache = cache
    return wrapper


if __name__ == "__main__":
    print("=== C3: memoize verification ===\n")

    # 1) The happy path works for distinct integer args.
    calls = []
    @memoize
    def add(a, b):
        calls.append((a, b))
        return a + b
    assert add(1, 2) == 3
    assert add(1, 2) == 3
    assert calls == [(1, 2)], calls
    print("1) distinct int args: correct, second call cached. calls =", calls)

    # 2) KEY-COLLISION BUG: different argument tuples stringify to the same
    #    key, so a stale value is returned for a different call.
    got = []
    @memoize
    def h(*args):
        got.append(args)
        return ("REAL", args)
    first = h("a,b")      # key "a,b" -> computes
    second = h("a", "b")  # key "a,b" -> COLLISION, returns the stale value
    print(f"2) h('a,b')      -> {first}")
    print(f"   h('a','b')    -> {second}")
    print(f"   h was actually called with: {got}")
    collided = (second == first) and (len(got) == 1)
    print(f"   => collision? {collided}  "
          f"(h('a','b') returned the value computed for h('a,b'))")

    # 3) Another collision: fn() vs fn("") both key to "".
    @memoize
    def g(*args):
        return args
    e1 = g()
    e2 = g("")
    print(f"3) g() -> {e1!r}   g('') -> {e2!r}   same cached value? {e1 == e2}")

    # 4) Keyword arguments are not supported at all.
    @memoize
    def k(a, b=0):
        return (a, b)
    try:
        k(1, b=2)
        print("4) kwargs: accepted (unexpected)")
    except TypeError as e:
        print(f"4) kwargs: BROKEN -> TypeError: {e}")

    # 5) Non-string args with equal str() also collide.
    @memoize
    def m(x):
        return type(x).__name__
    v1 = m(1)
    v2 = m("1")
    print(f"5) m(1) -> {v1!r}   m('1') -> {v2!r}   (int 1 and str '1' share key '1')")

    print()
    print("CONCLUSION: the decorator is NOT correct in general.")
    print("  - It works for the common case of distinct, unambiguous args,")
    print("  - but the string-joined key collides for different argument")
    print("    tuples (e.g. ('a,b',) vs ('a','b'); () vs ('',)), returning")
    print("    stale values, and it does not support keyword arguments.")
