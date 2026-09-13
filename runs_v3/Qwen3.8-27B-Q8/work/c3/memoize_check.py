"""C3: verdict on the memoize decorator.

The decorator:

    def memoize(fn):
        cache = {}
        def wrapper(*args):
            key = ",".join(str(a) for a in args)
            if key not in cache:
                cache[key] = fn(*args)
        return cache[key]
        wrapper.cache = cache
        return wrapper

Verdict: NOT correct. The cache key is not a well-defined function of the
arguments, so the wrapper can return a value that was computed for a *different*
input.
"""

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
    ok = True

    # --- Defect 1: key collision between different argument tuples ----------
    # f("a,b", "c") stringifies to "a,b,c"
    # f("a", "b,c") also stringifies to "a,b,c"
    # Different inputs, identical key -> the second call returns the first's
    # cached value.
    @memoize
    def f(a, b):
        return [a, b]

    first = f("a,b", "c")
    second = f("a", "b,c")
    print(f'f("a,b","c") = {first}')
    print(f'f("a","b,c") = {second}   (correct value would be ["a", "b,c"])')
    collision = (second != ["a", "b,c"])
    print(f"  -> key collision returned a wrong value: {collision}\n")
    ok = ok and collision

    # A numeric flavour of the same bug: (1, 23) vs (12, 3) are fine, but
    # (1, "2,3") vs ("1", "2,3") collide, and (1, 2, 3) vs (1, 23) do not --
    # the point is the mapping is not injective in general.
    @memoize
    def g(x, y):
        return (x, y)

    a = g(1, "2,3")     # key "1,2,3"
    b = g("1", "2,3")   # key "1,2,3"  -> collides with the int-1 call
    print(f'g(1,"2,3")   = {a}')
    print(f'g("1","2,3") = {b}   (correct value would be ("1", "2,3"))')
    collision2 = (b != ("1", "2,3"))
    print(f"  -> int/str collision returned a wrong value: {collision2}\n")
    ok = ok and collision2

    # --- Defect 2: keyword arguments are not supported -----------------------
    @memoize
    def h(a, b=0):
        return (a, b)

    try:
        h(a=5, b=6)
        kw_supported = True
    except TypeError as e:
        kw_supported = False
        print(f"  calling with keyword args raised TypeError: {e}\n")
    ok = ok and (not kw_supported)

    # --- The part that DOES work --------------------------------------------
    # For a fixed positional-args tuple with no ambiguity, it is consistent.
    calls = []
    def add_counting(x, y):
        calls.append((x, y))
        return x + y
    add_counting = memoize(add_counting)
    add_counting(2, 3)
    add_counting(2, 3)
    print(f"  repeated identical call computed once: {len(calls) == 1}")
    ok = ok and (len(calls) == 1)

    print("\n" + ("C3 DEMONSTRATION COMPLETE (decorator is INCORRECT)"
                  if ok else "C3 demonstration incomplete"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
