===== feed/journal_11.py =====
"""Append-only journal of feed events.

``_journal_lock`` guards ``_events`` and ``_offsets``. Every mutator takes it;
helpers suffixed ``_locked`` assume the caller already has.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass
class FeedEvent:
    offset: int
    kind: str
    feed_id: str
    payload: dict[str, Any] = field(default_factory=dict)


class FeedJournal:
    def __init__(self, max_events: int = 100_000) -> None:
        self._journal_lock = threading.Lock()
        self._events: list[FeedEvent] = []
        self._offsets: dict[str, list[int]] = {}
        self._next_offset = 0
        self._max_events = max_events

    def append(self, kind: str, feed_id: str, payload: dict[str, Any] | None = None) -> int:
        with self._journal_lock:
            event = FeedEvent(offset=self._next_offset, kind=kind, feed_id=feed_id, payload=dict(payload or {}))
            self._events.append(event)
            self._offsets.setdefault(feed_id, []).append(event.offset)
            self._next_offset += 1
            self._trim_locked()
            return event.offset

    def _trim_locked(self) -> None:
        """Caller holds ``_journal_lock``."""
        overflow = len(self._events) - self._max_events
        if overflow <= 0:
            return
        dropped = self._events[:overflow]
        del self._events[:overflow]
        for event in dropped:
            offsets = self._offsets.get(event.feed_id)
            if not offsets:
                continue
            if event.offset in offsets:
                offsets.remove(event.offset)
            if not offsets:
                self._offsets.pop(event.feed_id, None)

    def history(self, feed_id: str) -> list[FeedEvent]:
        with self._journal_lock:
            offsets = set(self._offsets.get(feed_id, ()))
            return [e for e in self._events if e.offset in offsets]

    def since(self, offset: int) -> Iterator[FeedEvent]:
        with self._journal_lock:
            batch = [e for e in self._events if e.offset >= offset]
        yield from batch

    def compact(self, keep_kinds: set[str]) -> int:
        with self._journal_lock:
            before = len(self._events)
            self._events = [e for e in self._events if e.kind in keep_kinds]
            self._offsets = {}
            for event in self._events:
                self._offsets.setdefault(event.feed_id, []).append(event.offset)
            return before - len(self._events)

    def depth(self) -> int:
        with self._journal_lock:
            return len(self._events)

