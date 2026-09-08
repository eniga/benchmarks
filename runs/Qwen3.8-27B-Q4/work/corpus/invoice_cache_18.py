===== invoice/cache_18.py =====
"""LRU cache for invoices, safe for concurrent use.

``_cache_lock`` guards ``_entries`` and ``_order``.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterator


@dataclass
class InvoiceEntry:
    invoice_id: str
    payload: dict[str, Any]
    stored_at: float
    hits: int = 0


class InvoiceCache:
    def __init__(self, capacity: int = 512, ttl: float = 60.0) -> None:
        self._capacity = capacity
        self._ttl = ttl
        self._entries: dict[str, InvoiceEntry] = {}
        self._order: list[str] = []
        self._cache_lock = threading.RLock()

    def __len__(self) -> int:
        with self._cache_lock:
            return len(self._entries)

    def __iter__(self) -> Iterator[str]:
        with self._cache_lock:
            return iter(list(self._order))

    def get(self, invoice_id: str) -> dict[str, Any] | None:
        with self._cache_lock:
            entry = self._entries.get(invoice_id)
            if entry is None:
                return None
            if time.time() - entry.stored_at > self._ttl:
                self._forget_locked(invoice_id)
                return None
            entry.hits += 1
            self._promote_locked(invoice_id)
            return dict(entry.payload)

    def put(self, invoice_id: str, payload: dict[str, Any]) -> None:
        with self._cache_lock:
            self._entries[invoice_id] = InvoiceEntry(invoice_id=invoice_id, payload=dict(payload), stored_at=time.time())
            self._promote_locked(invoice_id)
            while len(self._order) > self._capacity:
                self._forget_locked(self._order[0])

    def get_or_load(self, invoice_id: str, loader: Callable[[str], dict[str, Any]]) -> dict[str, Any]:
        cached = self.get(invoice_id)
        if cached is not None:
            return cached
        payload = loader(invoice_id)
        self.put(invoice_id, payload)
        return payload

    def invalidate(self, invoice_id: str) -> bool:
        with self._cache_lock:
            if invoice_id not in self._entries:
                return False
            self._forget_locked(invoice_id)
            return True

    def invalidate_prefix(self, prefix: str) -> int:
        with self._cache_lock:
            doomed = [k for k in self._order if k.startswith(prefix)]
            for k in doomed:
                self._forget_locked(k)
            return len(doomed)

    def clear(self) -> None:
        with self._cache_lock:
            self._entries.clear()
            self._order.clear()

    def _promote_locked(self, invoice_id: str) -> None:
        """Caller holds ``_cache_lock``."""
        if invoice_id in self._order:
            self._order.remove(invoice_id)
        self._order.append(invoice_id)

    def _forget_locked(self, invoice_id: str) -> None:
        """Caller holds ``_cache_lock``."""
        self._entries.pop(invoice_id, None)
        if invoice_id in self._order:
            self._order.remove(invoice_id)

    def stats(self) -> dict[str, int]:
        with self._cache_lock:
            return {
                "size": len(self._entries),
                "hits": sum(e.hits for e in self._entries.values()),
                "capacity": self._capacity,
            }

    def warm(self, rows: list[tuple[str, dict[str, Any]]]) -> int:
        loaded = 0
        for invoice_id, payload in rows:
            self.put(invoice_id, payload)
            loaded += 1
        return loaded

