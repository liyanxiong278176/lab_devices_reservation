from __future__ import annotations

from time import perf_counter
from types import SimpleNamespace

import psutil
import pytest
from app.core.metrics import MetricsRegistry
from sqlalchemy import create_engine


def test_metrics_registry_rejects_invalid_names_labels_collisions_and_excess_series() -> None:
    with pytest.raises(ValueError, match="max_series must be positive"):
        MetricsRegistry(max_series=0)
    registry = MetricsRegistry(max_series=1)
    registry.increment("bad metric")
    registry.increment("bad_label", labels={"not-valid": "x"})
    registry.increment("reserved_label", labels={"__name__": "forbidden"})
    registry.increment("invalid_counter", -1)
    registry.increment("invalid_counter", float("nan"))
    registry.observe("invalid_histogram", float("inf"))
    registry.set_gauge("invalid_gauge", float("nan"))

    registry.increment("bounded_events_total", labels={"kind": "first"})
    registry.increment("bounded_events_total", labels={"kind": "first"})
    registry.increment("bounded_events_total", labels={"kind": "second"})
    registry.observe("bounded_events_total", 1, labels={"kind": "first"})
    registry.increment("bounded_events_total", labels={"other": "first"})
    registry.observe("new_family", 1)

    rendered = registry.render_prometheus()
    assert 'bounded_events_total{kind="first"} 2.0' in rendered
    assert 'kind="second"' not in rendered
    assert "bad_metric" not in rendered
    assert "invalid_counter" not in rendered
    assert "new_family" not in rendered

    gauge_registry = MetricsRegistry()
    gauge_registry.set_gauge("bounded_gauge", 3)
    gauge_registry.set_gauge("invalid_gauge_label", 3, labels={"bad-name": "x"})
    assert "bounded_gauge 3.0" in gauge_registry.render_prometheus()
    assert "invalid_gauge_label" not in gauge_registry.render_prometheus()


def test_metrics_handle_engines_without_a_pool_or_event_dispatch() -> None:
    registry = MetricsRegistry()
    registry.monitor_sqlalchemy_pool(SimpleNamespace(pool=None))

    pool = SimpleNamespace(size=8)
    engine_without_dispatch = SimpleNamespace(pool=pool)
    registry.monitor_sqlalchemy_pool(engine_without_dispatch)

    assert registry._pool_value("size") == 8
    assert registry._monitored_engines == set()

    engine = create_engine("sqlite://")
    try:
        registry.monitor_sqlalchemy_pool(engine)
        registry.monitor_sqlalchemy_pool(engine)
        assert registry._monitored_engines == {id(engine)}
    finally:
        engine.dispose()


def test_sql_statement_metrics_cover_other_operations_and_missing_timing_state() -> None:
    registry = MetricsRegistry()
    without_start = SimpleNamespace()
    registry._after_cursor_execute(None, None, "", None, without_start, False)

    context = SimpleNamespace()
    registry._before_cursor_execute(None, None, "PRAGMA journal_mode", None, context, False)
    assert context._lab_metrics_operation == "OTHER"
    registry._after_cursor_execute(None, None, "", None, context, False)

    registry._after_cursor_execute(
        None,
        None,
        "",
        None,
        SimpleNamespace(_lab_metrics_started_at=perf_counter() - 0.01),
        False,
    )
    rendered = registry.render_prometheus()
    assert 'db_statements_total{operation="OTHER"} 2.0' in rendered
    assert registry.registry is not None


def test_pool_gauges_ignore_unsupported_properties_and_clamp_overflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class PartialPool:
        size = 6

        def checkedout(self) -> int:
            return 2

        def overflow(self) -> int:
            return -3

    class BrokenPool:
        @property
        def size(self) -> int:
            raise NotImplementedError

        @property
        def checkedout(self) -> int:
            raise ValueError

    registry = MetricsRegistry()
    registry._pools = {1: PartialPool(), 2: BrokenPool(), 3: object()}
    assert registry._pool_value("size") == 6
    assert registry._pool_value("checkedout") == 2
    assert registry._pool_value("overflow") == 0

    def cpu_unavailable(*_args: object, **_kwargs: object) -> float:
        raise psutil.AccessDenied(pid=1)

    monkeypatch.setattr(registry._process, "cpu_percent", cpu_unavailable)
    assert "lab_process_cpu_percent" in registry.render_prometheus()
