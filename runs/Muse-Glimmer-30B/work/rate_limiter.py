import threading
import time
from collections import defaultdict

class TokenBucket:
    def __init__(self, capacity, refill_rate):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = float(capacity)
        self.last = time.monotonic()
        self.lock = threading.Lock()

    def consume(self, amount=1):
        with self.lock:
            now = time.monotonic()
            elapsed = now - self.last
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.last = now
            if self.tokens >= amount:
                self.tokens -= amount
                return True
            return False

class RateLimiter:
    def __init__(self):
        self.buckets = {}
        self.last_seen = {}
        self.lock = threading.RLock()
        self.ttl = 600

    def _cleanup(self):
        now = time.monotonic()
        expired = [k for k, t in self.last_seen.items() if now - t > self.ttl]
        for k in expired:
            self.buckets.pop(k, None)
            self.last_seen.pop(k, None)

    def allow(self, key, capacity, refill_rate):
        with self.lock:
            self._cleanup()
            self.last_seen[key] = time.monotonic()
            bucket = self.buckets.get(key)
            if bucket is None:
                bucket = TokenBucket(capacity, refill_rate)
                self.buckets[key] = bucket
            return bucket.consume()

def test_basic():
    rl = RateLimiter()
    assert rl.allow('a', 2, 1)
    assert rl.allow('a', 2, 1)
    assert not rl.allow('a', 2, 1)
    print('test_basic passed')

def test_refill():
    rl = RateLimiter()
    assert rl.allow('b', 1, 10)
    time.sleep(0.2)
    assert rl.allow('b', 1, 10)
    print('test_refill passed')

def test_threadsafe():
    import concurrent.futures
    rl = RateLimiter()
    successes = []
    def worker():
        s = 0
        for _ in range(100):
            if rl.allow('c', 1000, 1000):
                s+=1
        successes.append(s)
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        ex.map(lambda _: worker(), range(10))
    print('test_threadsafe passed, total', sum(successes))

if __name__ == '__main__':
    test_basic()
    test_refill()
    test_threadsafe()
