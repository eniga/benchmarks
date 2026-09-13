import time
import threading
from collections import deque

class ConnectionPool:
    def __init__(self, max_size, factory, closer):
        self.max_size = max_size
        self.factory = factory
        self.closer = closer
        self.lock = threading.Lock()
        self.available = deque()  # (conn, release_time)
        self.in_use = set()
        self.waiters = deque()  # Event objects

    def acquire(self, timeout=None):
        deadline = None
        if timeout is not None:
            deadline = time.monotonic() + timeout
        while True:
            conn_to_close = None
            need_create = False
            ev = None
            with self.lock:
                # Try to reuse an available connection
                if self.available:
                    conn, ts = self.available.popleft()
                    if time.monotonic() - ts > 60:
                        # idle too long, close lazily
                        conn_to_close = conn
                        # will close outside lock and retry
                    else:
                        self.in_use.add(conn)
                        return conn
                # No usable available connection
                if len(self.in_use) < self.max_size:
                    need_create = True
                else:
                    # Need to wait for a release
                    ev = threading.Event()
                    self.waiters.append(ev)
            # Outside lock: handle stale close or creation or waiting
            if conn_to_close is not None:
                # Close outside lock as required by invariant
                try:
                    self.closer(conn_to_close)
                except Exception:
                    pass
                # Loop again to try another connection
                continue
            if need_create:
                # Create connection outside lock
                conn = self.factory()
                with self.lock:
                    # Re-check size under lock to avoid race
                    if len(self.in_use) >= self.max_size:
                        # Rare race, close the newly created connection and retry
                        self.closer(conn)
                        continue
                    self.in_use.add(conn)
                    return conn
            # Wait for a connection to be released
            if ev is None:
                # Should not happen
                continue
            remaining = None
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    # Timeout already elapsed
                    with self.lock:
                        try:
                            self.waiters.remove(ev)
                        except ValueError:
                            pass
                    raise TimeoutError("acquire timeout")
            if ev.wait(timeout=remaining):
                # Connection handed to us via ev.conn
                return ev.conn
            else:
                # Timeout
                with self.lock:
                    try:
                        self.waiters.remove(ev)
                    except ValueError:
                        pass
                raise TimeoutError("acquire timeout")

    def release(self, conn):
        with self.lock:
            self.in_use.discard(conn)
            if self.waiters:
                ev = self.waiters.popleft()
                ev.conn = conn
                ev.set()
            else:
                self.available.append((conn, time.monotonic()))
