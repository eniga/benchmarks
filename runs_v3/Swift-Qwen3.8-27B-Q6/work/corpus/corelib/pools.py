"""Worker-pool plumbing.  Pool sizing lives with each pool's own module."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class PoolSpec:
    name: str
    workers: int
    prefetch_depth: int
    enabled: bool = True
    tags: tuple[str, ...] = field(default_factory=tuple)


class WorkerPool:
    def __init__(self, spec: PoolSpec) -> None:
        self.spec = spec
        self._lock = threading.RLock()
        self._started = False

    def start(self) -> bool:
        if not self.spec.enabled:
            return False
        with self._lock:
            self._started = True
        return True

    def describe(self) -> str:
        state = "started" if self._started else "idle"
        return f"{self.spec.name}<{self.spec.workers}x{self.spec.prefetch_depth},{state}>"

