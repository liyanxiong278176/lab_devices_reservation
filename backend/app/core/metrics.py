from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping
from threading import Lock


def _label_text(labels: Mapping[str, object] | None) -> str:
    if not labels:
        return ""
    parts = []
    for key, value in sorted(labels.items()):
        escaped = str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        parts.append(f'{key}="{escaped}"')
    return "{" + ",".join(parts) + "}"


class MetricsRegistry:
    """Small dependency-free metrics registry for the single-service runtime.

    The registry intentionally exposes Prometheus text without adding another
    runtime dependency. It is process-local; deployment-level aggregation is
    outside this application's reliability scope.
    """

    def __init__(self, *, max_series: int = 2048) -> None:
        if max_series < 1:
            raise ValueError("max_series must be positive")
        self._lock = Lock()
        self._max_series = max_series
        self._series: set[tuple[str, str, tuple[tuple[str, str], ...]]] = set()
        self._counters: defaultdict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(
            float
        )
        self._histograms: defaultdict[tuple[str, tuple[tuple[str, str], ...]], dict[str, float]] = (
            defaultdict(lambda: {"count": 0.0, "sum": 0.0})
        )

    def increment(
        self,
        name: str,
        value: float = 1.0,
        labels: Mapping[str, object] | None = None,
    ) -> None:
        normalized = tuple(sorted((key, str(item)) for key, item in (labels or {}).items()))
        with self._lock:
            key = (name, normalized)
            series_key = ("counter", *key)
            if series_key not in self._series:
                if len(self._series) >= self._max_series:
                    return
                self._series.add(series_key)
            self._counters[key] += value

    def observe(
        self,
        name: str,
        value: float,
        labels: Mapping[str, object] | None = None,
    ) -> None:
        normalized = tuple(sorted((key, str(item)) for key, item in (labels or {}).items()))
        with self._lock:
            key = (name, normalized)
            series_key = ("histogram", *key)
            if series_key not in self._series:
                if len(self._series) >= self._max_series:
                    return
                self._series.add(series_key)
            item = self._histograms[key]
            item["count"] += 1
            item["sum"] += value

    def render_prometheus(self) -> str:
        lines: list[str] = []
        with self._lock:
            counters = list(self._counters.items())
            histograms = list(self._histograms.items())
        names = {name for (name, _), _ in counters} | {name for (name, _), _ in histograms}
        for name in sorted(names):
            lines.append(f"# TYPE {name} gauge")
            for (metric_name, labels), value in counters:
                if metric_name == name:
                    lines.append(f"{name}{_label_text(dict(labels))} {value:g}")
            for (metric_name, labels), value in histograms:
                if metric_name == name:
                    label_text = _label_text(dict(labels))
                    lines.append(f"{name}_count{label_text} {value['count']:g}")
                    lines.append(f"{name}_sum{label_text} {value['sum']:g}")
        return "\n".join(lines) + ("\n" if lines else "")


def percentiles(values: list[float]) -> dict[str, float]:
    """Return deterministic percentile estimates for test/benchmark reports."""

    if not values:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
    ordered = sorted(values)

    def pick(ratio: float) -> float:
        index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * ratio) - 1))
        return ordered[index]

    return {"p50": pick(0.50), "p95": pick(0.95), "p99": pick(0.99)}
