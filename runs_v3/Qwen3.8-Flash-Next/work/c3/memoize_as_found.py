"""Task C3 - the memoize decorator as found, plus a corrected version.

The version under review (verbatim from the codebase) is kept as ``memoize``
in memoize_as_found.py; ``memoize_fixed`` is what replaces it.
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


def memoize_fixed(fn=None, *, maxsize=None, thread_safe=False):
    """Memoize that keys on the real arguments.

    * args and kwargs both participate in the key (no signature change)
    * the key is the argument tuple itself, so 1 and "1" cannot collide and
      "," cannot be smuggled through a string argument
    * functools.wraps preserves __name__/__doc__/__qualname__ and the
      inspect.signature of the wrapped function
    * optional LRU bound and a lock, both opt-in so behaviour is unchanged
    """

    import functools
    import threading

    def decorator(func):
        cache = {}
        order = []                      # insertion order for the optional bound
        lock = threading.Lock()

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                key = (args, tuple(sorted(kwargs.items())))
                hash(key)
            except TypeError:
                # unhashable argument: no caching is possible, just call through
                return func(*args, **kwargs)

            def lookup():
                if key in cache:
                    if maxsize:
                        order.remove(key)
                        order.append(key)
                    return True, cache[key]
                return False, None

            def store(value):
                cache[key] = value
                if maxsize:
                    order.append(key)
                    while len(order) > maxsize:
                        oldest = order.pop(0)
                        cache.pop(oldest, None)

            if not thread_safe:
                hit, value = lookup()
                if hit:
                    return value
                value = func(*args, **kwargs)
                store(value)
                return value
            # ``thread_safe=True``: the lock covers lookup *and* the call, so
            # the wrapped function runs at most once per key.  Serialising the
            # call is the price of that guarantee; a production version would
            # use a per-key in-flight marker instead.
            with lock:
                hit, value = lookup()
                if hit:
                    return value
                value = func(*args, **kwargs)
                store(value)
                return value

        wrapper.cache = cache
        return wrapper

    if fn is not None:
        return decorator(fn)
    return decorator
