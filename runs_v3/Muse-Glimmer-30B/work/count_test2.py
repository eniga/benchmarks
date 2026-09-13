import random
import time

class Fenwick:
    def __init__(self, n):
        self.n = n
        self.bit = [0]*(n+1)
    def add(self, idx, delta):
        while idx <= self.n:
            self.bit[idx] += delta
            idx += idx & -idx
    def sum(self, idx):
        s = 0
        while idx > 0:
            s += self.bit[idx]
            idx -= idx & -idx
        return s

def count_smaller_before_original(values):
    out = []
    for i, v in enumerate(values):
        n = 0
        for j in range(i):
            if values[j] < v:
                n += 1
        out.append(n)
    return out

def count_smaller_before_fenwick(values):
    # coordinate compression
    uniq = sorted(set(values))
    rank = {v:i+1 for i,v in enumerate(uniq)}
    ft = Fenwick(len(uniq))
    out = []
    for v in values:
        r = rank[v]
        cnt = ft.sum(r-1)
        out.append(cnt)
        ft.add(r, 1)
    return out

def test_correctness():
    for _ in range(200):
        n = random.randint(0, 1000)
        vals = [random.randint(-1000, 1000) for _ in range(n)]
        a = count_smaller_before_original(vals)
        b = count_smaller_before_fenwick(vals)
        if a != b:
            print("Mismatch!")
            return False
    print("Correctness passed")
    return True

def benchmark():
    for size in [1000, 5000, 20000, 50000, 100000, 200000]:
        vals = [random.randint(-10**9, 10**9) for _ in range(size)]
        t0 = time.perf_counter()
        count_smaller_before_fenwick(vals)
        t1 = time.perf_counter()
        print(f"size {size}: fenwick {t1-t0:.4f}s")

if __name__ == "__main__":
    test_correctness()
    benchmark()
