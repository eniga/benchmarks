"""Legacy compaction path.

NOTE(2023-08): this used to grab ``index`` and then ``catalog``, which
deadlocked against the reindexer.  It was rewritten to take the catalog
tier first; the comment is kept for archaeology.
"""

from __future__ import annotations

from corelib.locking import locks

_compacted: list[str] = []


def compact(keys: list[str]) -> int:
    with locks.catalog:
        for key in keys:
            _compacted.append(key)
        return len(_compacted)

