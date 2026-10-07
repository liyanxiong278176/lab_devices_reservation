from __future__ import annotations

import asyncio
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import app.main as main
import pytest
from app.core.settings import Settings
from app.infrastructure.db import bootstrap, operational_bootstrap
from app.infrastructure.db import session as db_session
from app.infrastructure.tasks import worker as worker_module


class FakeRelay:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.args = args
        self.kwargs = kwargs
        self.started = False
        self.stopped = False
        self.metrics: object | None = None

    def set_metrics(self, metrics: object | None) -> None:
        self.metrics = metrics

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


def _dev_settings(*, workers: bool = False) -> Settings:
    return Settings(
        environment="dev",
        _env_file=None,
        mysql_dsn="sqlite+aiosqlite:///:memory:",
        enable_workers=workers,
        redis_url="redis://localhost/15",
    )


@pytest.mark.asyncio
async def test_lifespan_skips_runtime_bootstrap_in_test_and_disposes_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = main.create_app(Settings(environment="test", _env_file=None))
    dispose_engine = AsyncMock()
    dispose_redis = AsyncMock()
    monkeypatch.setattr(main, "dispose_app_engine", dispose_engine)
    monkeypatch.setattr(main, "dispose_app_redis", dispose_redis)

    async with main.lifespan(app):
        assert not hasattr(app.state, "notification_relay")

    dispose_engine.assert_awaited_once_with(app)
    dispose_redis.assert_awaited_once_with(app)


@pytest.mark.asyncio
async def test_lifespan_bootstraps_non_test_runtime_and_stops_relay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = main.create_app(_dev_settings())
    metrics = SimpleNamespace(monitor_sqlalchemy_pool=Mock())
    app.state.metrics = metrics
    engine = object()
    factory = object()
    calls: list[object] = []
    monkeypatch.setattr(db_session, "build_engine", lambda settings: engine)
    monkeypatch.setattr(db_session, "build_session_factory", lambda received: factory)
    ensure_admin = AsyncMock(side_effect=lambda *_: calls.append("admin"))
    ensure_metadata = AsyncMock(side_effect=lambda *_: calls.append("metadata"))
    monkeypatch.setattr(bootstrap, "ensure_bootstrap_admin", ensure_admin)
    monkeypatch.setattr(operational_bootstrap, "ensure_operational_metadata", ensure_metadata)
    monkeypatch.setattr(main, "get_redis_for_app", lambda received: "redis-stub")
    relay = FakeRelay()
    relay_kwargs: dict[str, object] = {}

    def create_relay(*_args: object, **kwargs: object) -> FakeRelay:
        relay_kwargs.update(kwargs)
        return relay

    monkeypatch.setattr(main, "RedisNotificationRelay", create_relay)
    dispose_engine = AsyncMock()
    dispose_redis = AsyncMock()
    monkeypatch.setattr(main, "dispose_app_engine", dispose_engine)
    monkeypatch.setattr(main, "dispose_app_redis", dispose_redis)

    async with main.lifespan(app):
        assert app.state.db_engine is engine
        assert app.state.session_factory is factory
        assert app.state.notification_relay is relay
        assert relay.started is True
        assert relay.metrics is metrics
        assert relay_kwargs["group_id"] == app.state.settings.notification_stream_group_id

    metrics.monitor_sqlalchemy_pool.assert_called_once_with(engine)
    ensure_admin.assert_awaited_once_with(factory, app.state.settings)
    ensure_metadata.assert_awaited_once_with(factory, app.state.settings)
    assert calls == ["admin", "metadata"]
    assert relay.stopped is True
    dispose_engine.assert_awaited_once_with(app)
    dispose_redis.assert_awaited_once_with(app)


@pytest.mark.asyncio
async def test_lifespan_reuses_preconfigured_engine_and_session_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = main.create_app(_dev_settings())
    engine = SimpleNamespace(dispose=AsyncMock())
    factory = object()
    app.state.db_engine = engine
    app.state.session_factory = factory
    app.state.metrics = SimpleNamespace(monitor_sqlalchemy_pool=Mock())
    monkeypatch.setattr(db_session, "build_engine", Mock(side_effect=AssertionError))
    monkeypatch.setattr(db_session, "build_session_factory", Mock(side_effect=AssertionError))
    monkeypatch.setattr(bootstrap, "ensure_bootstrap_admin", AsyncMock())
    monkeypatch.setattr(operational_bootstrap, "ensure_operational_metadata", AsyncMock())
    monkeypatch.setattr(main, "get_redis_for_app", lambda received: object())
    relay = FakeRelay()
    monkeypatch.setattr(main, "RedisNotificationRelay", lambda *args, **kwargs: relay)
    dispose_redis = AsyncMock()
    monkeypatch.setattr(main, "dispose_app_redis", dispose_redis)

    async with main.lifespan(app):
        assert app.state.db_engine is engine
        assert app.state.session_factory is factory

    app.state.metrics.monitor_sqlalchemy_pool.assert_called_once_with(engine)
    engine.dispose.assert_awaited_once()
    dispose_redis.assert_awaited_once_with(app)


@pytest.mark.asyncio
async def test_lifespan_starts_and_cancels_worker_background_loops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = main.create_app(_dev_settings(workers=True))
    app.state.metrics = SimpleNamespace(monitor_sqlalchemy_pool=Mock())
    engine = SimpleNamespace(dispose=AsyncMock())
    monkeypatch.setattr(db_session, "build_engine", lambda settings: engine)
    monkeypatch.setattr(db_session, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(bootstrap, "ensure_bootstrap_admin", AsyncMock())
    monkeypatch.setattr(operational_bootstrap, "ensure_operational_metadata", AsyncMock())
    monkeypatch.setattr(main, "get_redis_for_app", lambda received: object())
    relay = FakeRelay()
    monkeypatch.setattr(main, "RedisNotificationRelay", lambda *args, **kwargs: relay)

    worker = SimpleNamespace(start=AsyncMock(), stop=AsyncMock())
    monkeypatch.setattr(worker_module, "OutboxWorker", lambda received: worker)

    async def wait_forever(_app: object) -> None:
        await asyncio.Event().wait()

    retention_stub = ModuleType("app.ai.retention")
    retention_stub.ai_retention_loop = wait_forever
    uploads_stub = ModuleType("app.core.uploads")
    uploads_stub.upload_cleanup_loop = wait_forever
    monkeypatch.setitem(sys.modules, "app.ai.retention", retention_stub)
    monkeypatch.setitem(sys.modules, "app.core.uploads", uploads_stub)

    async with main.lifespan(app):
        worker.start.assert_awaited_once()
        assert app.state.notification_relay is relay

    worker.stop.assert_awaited_once()
    assert relay.stopped is True


def test_notification_stream_is_an_exempt_http_sse_route() -> None:
    app = main.create_app(Settings(environment="test", _env_file=None))
    paths = app.openapi()["paths"]
    assert "/api/v2/notifications/stream" in paths
    assert "/api/v2/ws" not in paths

    capacity = next(
        item for item in app.user_middleware if item.cls is main.RequestCapacityMiddleware
    )
    assert "/api/v2/notifications/stream" in capacity.kwargs["bypass_paths"]
