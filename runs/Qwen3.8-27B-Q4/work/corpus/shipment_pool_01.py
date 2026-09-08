===== shipment/pool_01.py =====
"""Bounded worker pool for shipment processing.

``_pool_lock`` guards ``_idle``, ``_busy`` and ``_waiters``; ``_ready`` is the
condition used to hand a slot to a blocked caller.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass


class ShipmentPoolExhausted(RuntimeError):
    pass


@dataclass
class ShipmentSlot:
    index: int
    leased_to: str | None = None
    leases: int = 0


class ShipmentPool:
    def __init__(self, size: int = 8) -> None:
        self._pool_lock = threading.Lock()
        self._ready = threading.Condition(self._pool_lock)
        self._idle: list[ShipmentSlot] = [ShipmentSlot(index=i) for i in range(size)]
        self._busy: dict[int, ShipmentSlot] = {}
        self._waiters = 0
        self._closed = False

    def acquire(self, owner: str, timeout: float | None = None) -> ShipmentSlot:
        with self._ready:
            self._waiters += 1
            try:
                while not self._idle:
                    if self._closed:
                        raise ShipmentPoolExhausted("pool closed")
                    if not self._ready.wait(timeout):
                        raise ShipmentPoolExhausted("timed out waiting for a slot")
                slot = self._idle.pop()
                slot.leased_to = owner
                slot.leases += 1
                self._busy[slot.index] = slot
                return slot
            finally:
                self._waiters -= 1

    def release(self, slot: ShipmentSlot) -> None:
        with self._ready:
            self._busy.pop(slot.index, None)
            slot.leased_to = None
            self._idle.append(slot)
            self._ready.notify()

    @contextmanager
    def lease(self, owner: str, timeout: float | None = None):
        slot = self.acquire(owner, timeout)
        try:
            yield slot
        finally:
            self.release(slot)

    def close(self) -> None:
        with self._ready:
            self._closed = True
            self._ready.notify_all()

    def in_use(self) -> int:
        with self._pool_lock:
            return len(self._busy)

    def describe(self) -> str:
        with self._pool_lock:
            return f"ShipmentPool(idle={len(self._idle)}, busy={len(self._busy)}, waiters={self._waiters})"

    def drain(self) -> list[int]:
        with self._pool_lock:
            drained = [slot.index for slot in self._idle]
            self._idle.clear()
            return drained

