===== sensor/metrics_17.py =====
"""Counters and histograms for the sensor subsystem.

``_metrics_lock`` guards ``_counters``, ``_gauges`` and ``_buckets``.
"""

from __future__ import annotations

import bisect
import threading
from typing import Sequence

DEFAULT_BUCKETS: Sequence[float] = (0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0)


class SensorMetrics:
    def __init__(self, buckets: Sequence[float] = DEFAULT_BUCKETS) -> None:
        self._metrics_lock = threading.Lock()
        self._counters: dict[str, int] = {}
        self._gauges: dict[str, float] = {}
        self._bounds = list(buckets)
        self._buckets: list[int] = [0] * (len(self._bounds) + 1)
        self._observations = 0

    def incr(self, name: str, by: int = 1) -> None:
        with self._metrics_lock:
            self._counters[name] = self._counters.get(name, 0) + by

    def set_gauge(self, name: str, value: float) -> None:
        with self._metrics_lock:
            self._gauges[name] = value

    def observe(self, seconds: float) -> None:
        index = bisect.bisect_left(self._bounds, seconds)
        with self._metrics_lock:
            self._buckets[index] += 1
            self._observations += 1

    def counter(self, name: str) -> int:
        with self._metrics_lock:
            return self._counters.get(name, 0)

    def snapshot(self) -> dict[str, object]:
        with self._metrics_lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "buckets": list(self._buckets),
                "observations": self._observations,
            }

    def reset(self) -> None:
        with self._metrics_lock:
            self._counters.clear()
            self._gauges.clear()
            self._buckets = [0] * (len(self._bounds) + 1)
            self._observations = 0

    def render_prometheus(self, prefix: str = "sensor") -> str:
        snap = self.snapshot()
        lines: list[str] = []
        for name, value in sorted(snap["counters"].items()):  # type: ignore[union-attr]
            lines.append(f"{prefix}_{name}_total {value}")
        for name, value in sorted(snap["gauges"].items()):  # type: ignore[union-attr]
            lines.append(f"{prefix}_{name} {value}")
        return "\n".join(lines)

