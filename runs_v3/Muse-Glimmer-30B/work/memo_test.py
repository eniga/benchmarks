def memoize(fn):
    cache = {}
    def wrapper(*args):
        key = ",".join(str(a) for a in args)
        if key not in cache:
            cache[key] = fn(*args)
        return cache[key]
    wrapper.cache = cache
    return wrapper

@memoize
def add(a, b):
    return a + b

# Test collision
print(add(1, 12))  # key "1,12"
# print(add(1, 1, 2))  # key "1,1,2" different
# Collision example: args ('a,b',) vs ('a','b')
@memoize
def concat(*args):
    return ''.join(args)

print("Collision test:")
print(concat('a,b'))  # key "a,b"
print(concat('a','b'))  # key "a,b" same -> returns cached wrong
print("Cache keys:", list(concat.cache.keys()))
