from __future__ import annotations

import math
import os
import re
from collections.abc import Mapping
from threading import Lock
from time import perf_counter

import psutil
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    GCCollector,
    Histogram,
    PlatformCollector,
    generate_latest,
)
from sqlalchemy import event

_METRIC_NAME = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
_LABEL_NAME = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_HTTP_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


class MetricsRegistry:
    """Bounded Prometheus registry for the single-process FastAPI runtime."""

    def __init__(self, *, max_series: int = 4096) -> None:
        if max_series < 1:
            raise ValueError("max_series must be positive")
        self._lock = Lock()
        self._max_series = max_series
        self._series: set[tuple[str, str, tuple[tuple[str, str], ...]]] = set()
        self._families: dict[str, tuple[str, tuple[str, ...], object]] = {}
        self._registry = CollectorRegistry()
        GCCollector(registry=self._registry)
        PlatformCollector(registry=self._registry)
        self._process = psutil.Process(os.getpid())
        self._process.cpu_percent(interval=None)

        self._process_cpu = Gauge(
            "lab_process_cpu_percent",
            "CPU utilization of the FastAPI process as a percentage.",
            registry=self._registry,
        )
        self._process_memory = Gauge(
            "lab_process_resident_memory_bytes",
            "Resident memory used by the FastAPI process, in bytes.",
            registry=self._registry,
        )
        self._process_threads = Gauge(
            "lab_process_threads",
            "Number of threads in the FastAPI process.",
            registry=self._registry,
        )
        self._pools: dict[int, object] = {}
        self._monitored_engines: set[int] = set()
        Gauge(
            "lab_db_pool_size",
            "Configured SQLAlchemy database connection pool size.",
            registry=self._registry,
        ).set_function(lambda: self._pool_value("size"))
        Gauge(
            "lab_db_pool_checked_out",
            "Number of SQLAlchemy database connections currently checked out.",
            registry=self._registry,
        ).set_function(lambda: self._pool_value("checkedout"))
        Gauge(
            "lab_db_pool_overflow",
            "Number of SQLAlchemy database connections above the base pool size.",
            registry=self._registry,
        ).set_function(lambda: self._pool_value("overflow"))

    def increment(
        self,
        name: str,
        value: float = 1.0,
        labels: Mapping[str, object] | None = None,
    ) -> None:
        if not math.isfinite(value) or value < 0:
            return
        metric, normalized = self._metric(name, "counter", labels)
        if metric is None:
            return
        child = metric.labels(**normalized) if normalized else metric
        child.inc(value)

    def observe(
        self,
        name: str,
        value: float,
        labels: Mapping[str, object] | None = None,
    ) -> None:
        if not math.isfinite(value):
            return
        metric, normalized = self._metric(name, "histogram", labels)
        if metric is None:
            return
        child = metric.labels(**normalized) if normalized else metric
        child.observe(value)

    def set_gauge(
        self,
        name: str,
        value: float,
        labels: Mapping[str, object] | None = None,
    ) -> None:
        if not math.isfinite(value):
            return
        metric, normalized = self._metric(name, "gauge", labels)
        if metric is None:
            return
        child = metric.labels(**normalized) if normalized else metric
        child.set(value)

    def monitor_sqlalchemy_pool(self, engine: object) -> None:
        sync_engine = getattr(engine, "sync_engine", engine)
        pool = getattr(sync_engine, "pool", None)
        if pool is None:
            return
        with self._lock:
            self._pools[id(pool)] = pool
            if not hasattr(sync_engine, "dispatch"):
                return
            engine_key = id(sync_engine)
            if engine_key in self._monitored_engines:
                return
            self._monitored_engines.add(engine_key)
        event.listen(sync_engine, "before_cursor_execute", self._before_cursor_execute)
        event.listen(sync_engine, "after_cursor_execute", self._after_cursor_execute)

    @staticmethod
    def _before_cursor_execute(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        context: object,
        _executemany: bool,
    ) -> None:
        setattr(context, "_lab_metrics_started_at", perf_counter())
        operation = statement.lstrip().partition(" ")[0].upper()
        if operation not in {"SELECT", "INSERT", "UPDATE", "DELETE", "REPLACE"}:
            operation = "OTHER"
        setattr(context, "_lab_metrics_operation", operation)

    def _after_cursor_execute(
        self,
        _connection: object,
        _cursor: object,
        _statement: str,
        _parameters: object,
        context: object,
        _executemany: bool,
    ) -> None:
        started_at = getattr(context, "_lab_metrics_started_at", None)
        if started_at is None:
            return
        operation = str(getattr(context, "_lab_metrics_operation", "OTHER"))
        labels = {"operation": operation}
        self.observe("db_statement_duration_seconds", perf_counter() - started_at, labels)
        self.increment("db_statements_total", labels=labels)

    def render_prometheus(self) -> str:
        try:
            self._process_cpu.set(self._process.cpu_percent(interval=None))
            self._process_memory.set(self._process.memory_info().rss)
            self._process_threads.set(self._process.num_threads())
        except psutil.Error:
            pass
        return generate_latest(self._registry).decode("utf-8")

    @property
    def registry(self) -> CollectorRegistry:
        return self._registry

    def _pool_value(self, attribute: str) -> float:
        with self._lock:
            pools = tuple(self._pools.values())
        total = 0.0
        for pool in pools:
            try:
                value = getattr(pool, attribute)
                numeric_value = float(value() if callable(value) else value)
                # SQLAlchemy QueuePool.overflow() is negative while the base
                # pool still has unused slots; this gauge means extra conns.
                if attribute == "overflow":
                    numeric_value = max(0.0, numeric_value)
                total += numeric_value
            except (AttributeError, NotImplementedError, TypeError, ValueError):
                continue
        return total

    def _metric(
        self,
        name: str,
        kind: str,
        labels: Mapping[str, object] | None,
    ) -> tuple[object | None, dict[str, str]]:
        if not _METRIC_NAME.fullmatch(name):
            return None, {}
        normalized = tuple(sorted((str(key), str(value)) for key, value in (labels or {}).items()))
        label_names = tuple(key for key, _ in normalized)
        if any(not _LABEL_NAME.fullmatch(key) or key == "__name__" for key in label_names):
            return None, {}
        series_key = (kind, name, normalized)
        with self._lock:
            existing = self._families.get(name)
            if existing is not None:
                existing_kind, existing_labels, metric = existing
                if existing_kind != kind or existing_labels != label_names:
                    return None, {}
                if series_key not in self._series and len(self._series) >= self._max_series:
                    return None, {}
            else:
                if len(self._series) >= self._max_series:
                    return None, {}
                help_text = f"Application metric {name}."
                if kind == "counter":
                    metric = Counter(
                        name,
                        help_text,
                        labelnames=label_names,
                        registry=self._registry,
                    )
                elif kind == "histogram":
                    metric = Histogram(
                        name,
                        help_text,
                        labelnames=label_names,
                        buckets=_HTTP_LATENCY_BUCKETS,
                        registry=self._registry,
                    )
                else:
                    metric = Gauge(name, help_text, labelnames=label_names, registry=self._registry)
                self._families[name] = (kind, label_names, metric)
            self._series.add(series_key)
        return metric, dict(normalized)
