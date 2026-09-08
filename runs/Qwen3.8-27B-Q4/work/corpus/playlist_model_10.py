===== playlist/model_10.py =====
"""Pure helpers for playlist records. No shared state, no locks."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Iterable, Sequence

_Playlist_KEY = re.compile(r"^[a-z][a-z0-9_-]{2,63}$")


@dataclass(frozen=True)
class PlaylistRecord:
    playlist_id: str
    label: str
    amount_seconds: int
    tags: tuple[str, ...] = ()

    def with_tag(self, tag: str) -> "PlaylistRecord":
        if tag in self.tags:
            return self
        return replace(self, tags=self.tags + (tag,))

    def scaled(self, factor: float) -> "PlaylistRecord":
        return replace(self, amount_seconds=int(self.amount_seconds * factor))


def is_valid_playlist_id(value: str) -> bool:
    return bool(_Playlist_KEY.match(value))


def normalise_label(label: str) -> str:
    collapsed = re.sub(r"\s+", " ", label.strip())
    return collapsed[:120]


def parse_playlist(row: Sequence[str]) -> PlaylistRecord:
    if len(row) < 3:
        raise ValueError(f"short row: {row!r}")
    playlist_id, label, amount = row[0], row[1], row[2]
    if not is_valid_playlist_id(playlist_id):
        raise ValueError(f"bad playlist_id: {playlist_id!r}")
    tags = tuple(t for t in row[3:] if t)
    return PlaylistRecord(playlist_id=playlist_id, label=normalise_label(label), amount_seconds=int(amount), tags=tags)


def total_seconds(records: Iterable[PlaylistRecord]) -> int:
    return sum(r.amount_seconds for r in records)


def group_by_tag(records: Iterable[PlaylistRecord]) -> dict[str, list[PlaylistRecord]]:
    grouped: dict[str, list[PlaylistRecord]] = {}
    for record in records:
        for tag in record.tags or ("untagged",):
            grouped.setdefault(tag, []).append(record)
    return grouped


def top_playlists(records: Iterable[PlaylistRecord], limit: int = 10) -> list[PlaylistRecord]:
    return sorted(records, key=lambda r: r.amount_seconds, reverse=True)[:limit]


def diff_playlists(before: Iterable[PlaylistRecord], after: Iterable[PlaylistRecord]) -> dict[str, str]:
    lhs = {r.playlist_id: r for r in before}
    rhs = {r.playlist_id: r for r in after}
    changes: dict[str, str] = {}
    for playlist_id in sorted(set(lhs) | set(rhs)):
        if playlist_id not in lhs:
            changes[playlist_id] = "added"
        elif playlist_id not in rhs:
            changes[playlist_id] = "removed"
        elif lhs[playlist_id] != rhs[playlist_id]:
            changes[playlist_id] = "changed"
    return changes


def render_table(records: Sequence[PlaylistRecord]) -> str:
    if not records:
        return "(no playlists)"
    width = max(len(r.playlist_id) for r in records)
    lines = [f"{r.playlist_id:<{width}}  {r.amount_seconds:>12}  {r.label}" for r in records]
    return "\n".join(lines)

