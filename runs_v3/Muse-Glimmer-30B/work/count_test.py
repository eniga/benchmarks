import random
import time
import bisect

def count_smaller_before_original(values):
    out = []
    for i, v in enumerate(values):
        n = 0
        for j in range(i):
            if values[j] < v:
                n += 1
        out.append(n)
    return out

def count_smaller_before_optimized(values):
    out = []
    sorted_vals = []
    for v in values:
        # number of elements < v
        idx = bisect.bisect_left(sorted_vals, v)
        out.append(idx)
        bisect.insort(sorted_vals, v)
    return out

def test_correctness():
    for _ in range(100):
        n = random.randint(0, 500)
        vals = [random.randint(-1000, 1000) for _ in range(n)]
        a = count_smaller_before_original(vals)
        b = count_smaller_before_optimized(vals)
        if a != b:
            print("Mismatch!", vals, a, b)
            return False
    print("Correctness tests passed")
    return True

def benchmark():
    sizes = [1000, 5000, 20000, 50000, 100000, 200000]
    for size in sizes:
        vals = [random.randint(-10**9, 10**9) for _ in range(size)]
        # Original only for small sizes
        if size <= 20000:
            t0 = time.perf_counter()
            count_smaller_before_original(vals)
            t1 = time.perf_counter()
            orig_time = t1 - t0
        else:
            orig_time = None
        t0 = time.perf_counter()
        count_smaller_before_optimized(vals)
        t1 = time.perf_counter()
        opt_time = t1 - t0
        if orig_time is not None:
            print(f"size {size}: original {orig_time:.4f}s, optimized {opt_time:.4f}s")
        else:
            print(f"size {size}: original N/A, optimized {opt_time:.4f}s")

if __name__ == "__main__":
    test_correctness()
    benchmark()
