from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import app.core.uvicorn_loop as uvicorn_loop
import app.infrastructure.db.session as db_session
import pytest
from app.application.lifecycle import change_device_status
from app.core.client_ip import resolve_client_ip
from app.core.settings import Settings
from app.infrastructure.db.bootstrap import ensure_bootstrap_admin
from app.infrastructure.db.models import DeviceStatusHistory, Role, User
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError


@pytest.mark.parametrize(
    ("peer", "forwarded", "trusted", "expected"),
    [
        (None, "198.51.100.1", ["10.0.0.0/8"], "unknown"),
        ("not-an-ip", "198.51.100.1", ["10.0.0.0/8"], "not-an-ip"),
        ("10.0.0.2", "198.51.100.1", ["bad-cidr"], "10.0.0.2"),
        ("10.0.0.2", "x" * 1025, ["10.0.0.0/8"], "10.0.0.2"),
        (
            "10.0.0.2",
            ",".join(f"10.0.0.{index}" for index in range(1, 18)),
            ["10.0.0.0/8"],
            "10.0.0.2",
        ),
        (
            "10.0.0.2",
            "10.1.0.1, 10.2.0.2",
            ["10.0.0.0/8"],
            "10.1.0.1",
        ),
        (
            "10.0.0.2",
            "2001:db8::1, 10.1.0.1",
            ["10.0.0.0/8"],
            "2001:db8::1",
        ),
    ],
)
def test_client_ip_rejects_untrusted_or_malformed_forwarding_chains(
    peer: str | None,
    forwarded: str | None,
    trusted: list[str],
    expected: str,
) -> None:
    assert resolve_client_ip(peer, forwarded, trusted) == expected


def test_change_device_status_is_idempotent_for_same_status() -> None:
    device = SimpleNamespace(id=7, college_id=3, status="IDLE")
    session = SimpleNamespace(add=AsyncMock())

    changed = change_device_status(
        session,
        device,
        "IDLE",
        operator_id=9,
        reason="重复提交",
    )

    assert changed is False
    assert device.status == "IDLE"
    session.add.assert_not_called()


def test_change_device_status_records_the_transition() -> None:
    device = SimpleNamespace(id=7, college_id=3, status="IDLE")
    added: list[object] = []
    session = SimpleNamespace(add=added.append)

    changed = change_device_status(
        session,
        device,
        "MAINTENANCE",
        operator_id=9,
        reason="现场检查",
    )

    assert changed is True
    assert device.status == "MAINTENANCE"
    assert len(added) == 1
    history = added[0]
    assert isinstance(history, DeviceStatusHistory)
    assert (history.old_status, history.new_status) == ("IDLE", "MAINTENANCE")
    assert (history.operator_id, history.reason) == (9, "现场检查")


def test_platform_loop_factory_selects_each_platform_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    windows_loop = object()
    other_loop = object()
    monkeypatch.setattr(uvicorn_loop.sys, "platform", "win32")
    monkeypatch.setattr(
        uvicorn_loop.asyncio,
        "ProactorEventLoop",
        lambda: windows_loop,
        raising=False,
    )
    assert uvicorn_loop.platform_loop_factory() is windows_loop

    monkeypatch.setattr(uvicorn_loop.sys, "platform", "linux")
    monkeypatch.setattr(uvicorn_loop.asyncio, "new_event_loop", lambda: other_loop)
    assert uvicorn_loop.platform_loop_factory() is other_loop


def _valid_production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "environment": "prod",
        "cookie_secure": True,
        "jwt_secret": "independent-production-secret-value-0123456789",
        "mysql_dsn": "mysql+asyncmy://runtime:separate-db-credential@localhost/lab_reservation",
        "metrics_token": "m" * 40,
        "ai_api_key": "provider-key",
        "ai_embedding_api_key": "embedding-key",
        "ai_mineru_api_key": "mineru-key",
    }
    values.update(overrides)
    return Settings(**values)


def test_production_settings_security_branches() -> None:
    assert _valid_production_settings().environment == "prod"

    with pytest.raises(ValueError, match="COOKIE_SECURE"):
        _valid_production_settings(cookie_secure=False)
    with pytest.raises(ValueError, match="AI_API_KEY"):
        _valid_production_settings(ai_api_key=None)
    with pytest.raises(ValueError, match="AI_EMBEDDING_API_KEY"):
        _valid_production_settings(ai_embedding_api_key="   ")
    with pytest.raises(ValueError, match="AI_MINERU_API_KEY"):
        _valid_production_settings(ai_mineru_api_key="")
    with pytest.raises(ValueError, match="METRICS_TOKEN"):
        _valid_production_settings(metrics_token="short")
    with pytest.raises(ValueError, match="METRICS_TOKEN"):
        _valid_production_settings(metrics_token=None)


class _FakeSessionContext:
    def __init__(self, session: object) -> None:
        self.session = session
        self.entered = False
        self.exited = False

    async def __aenter__(self) -> object:
        self.entered = True
        return self.session

    async def __aexit__(self, *_exc: object) -> None:
        self.exited = True


def _request_with_state(state: object) -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(state=state))


@pytest.mark.asyncio
async def test_get_db_uses_existing_session_factory_without_rebuilding() -> None:
    session = object()
    context = _FakeSessionContext(session)
    calls = 0

    def factory() -> _FakeSessionContext:
        nonlocal calls
        calls += 1
        return context

    state = SimpleNamespace(session_factory=factory)
    dependency = db_session.get_db(_request_with_state(state))
    assert await anext(dependency) is session
    await dependency.aclose()

    assert calls == 1
    assert context.entered and context.exited


@pytest.mark.asyncio
async def test_get_db_builds_engine_factory_and_registers_pool_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = object()
    session = object()
    context = _FakeSessionContext(session)
    metrics = SimpleNamespace(monitor_sqlalchemy_pool=Mock())
    settings = Settings(environment="test", _env_file=None)
    def factory():
        return context
    monkeypatch.setattr(db_session, "build_engine", lambda received: engine)
    monkeypatch.setattr(db_session, "build_session_factory", lambda received: factory)
    state = SimpleNamespace(settings=settings, metrics=metrics)
    dependency = db_session.get_db(_request_with_state(state))

    assert await anext(dependency) is session
    await dependency.aclose()

    assert state.db_engine is engine
    assert state.session_factory is factory
    metrics.monitor_sqlalchemy_pool.assert_called_once_with(engine)
    assert context.entered and context.exited


@pytest.mark.asyncio
async def test_get_db_reuses_engine_when_metrics_are_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = object()
    session = object()
    context = _FakeSessionContext(session)
    def factory():
        return context
    monkeypatch.setattr(db_session, "build_session_factory", lambda received: factory)
    state = SimpleNamespace(settings=Settings(environment="test", _env_file=None), db_engine=engine)
    dependency = db_session.get_db(_request_with_state(state))

    assert await anext(dependency) is session
    await dependency.aclose()

    assert state.session_factory is factory
    assert context.entered and context.exited


@pytest.mark.asyncio
async def test_dispose_app_engine_only_disposes_an_existing_engine() -> None:
    engine = SimpleNamespace(dispose=AsyncMock())
    await db_session.dispose_app_engine(SimpleNamespace(state=SimpleNamespace(db_engine=engine)))
    engine.dispose.assert_awaited_once()
    await db_session.dispose_app_engine(SimpleNamespace(state=SimpleNamespace()))
    await db_session.dispose_app_engine(SimpleNamespace())


def test_build_engine_configures_sqlite_and_mysql_pools(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[tuple[object, dict[str, object]]] = []

    def fake_create_engine(dsn: object, **options: object) -> object:
        created.append((dsn, options))
        return object()

    monkeypatch.setattr(db_session, "create_async_engine", fake_create_engine)
    sqlite_settings = Settings(
        environment="test",
        _env_file=None,
        mysql_dsn="sqlite+aiosqlite:///:memory:",
        debug=True,
    )
    mysql_settings = Settings(
        environment="test",
        _env_file=None,
        mysql_dsn="mysql+asyncmy://runtime:pw@localhost/lab",
        db_pool_size=3,
        db_max_overflow=4,
        db_pool_recycle_seconds=55,
        db_pool_timeout_seconds=6,
    )

    db_session.build_engine(sqlite_settings)
    db_session.build_engine(mysql_settings)

    assert created[0][1] == {"echo": True, "pool_pre_ping": True}
    assert created[1][1] == {
        "echo": False,
        "pool_pre_ping": True,
        "isolation_level": "READ COMMITTED",
        "pool_size": 3,
        "max_overflow": 4,
        "pool_recycle": 55,
        "pool_timeout": 6,
    }


@pytest.mark.asyncio
async def test_bootstrap_admin_skips_when_password_is_not_configured(session_factory) -> None:
    settings = Settings(environment="test", _env_file=None, bootstrap_admin_password=None)
    await ensure_bootstrap_admin(session_factory, settings)

    async with session_factory() as session:
        assert await session.scalar(
            select(User).where(User.username == settings.bootstrap_admin_username)
        ) is None


@pytest.mark.asyncio
async def test_bootstrap_admin_skips_when_system_role_is_missing(session_factory) -> None:
    settings = Settings(
        environment="test",
        _env_file=None,
        bootstrap_admin_username="not-created",
        bootstrap_admin_password="strong-test-password",
    )
    await ensure_bootstrap_admin(session_factory, settings)

    async with session_factory() as session:
        assert await session.scalar(
            select(User).where(User.username == settings.bootstrap_admin_username)
        ) is None


@pytest.mark.asyncio
async def test_bootstrap_admin_rolls_back_a_concurrent_unique_username_winner() -> None:
    role = Role(role_code="SYS_ADMIN", role_name="系统管理员")

    class ConcurrentInsertSession:
        def __init__(self) -> None:
            self.scalar = AsyncMock(side_effect=[None, role])
            self.add = Mock()
            self.commit = AsyncMock(
                side_effect=IntegrityError("INSERT", {}, RuntimeError("duplicate username"))
            )
            self.rollback = AsyncMock()

        async def __aenter__(self) -> ConcurrentInsertSession:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

    fake_session = ConcurrentInsertSession()

    class Factory:
        def __call__(self) -> ConcurrentInsertSession:
            return fake_session

    settings = Settings(
        environment="test",
        _env_file=None,
        bootstrap_admin_username="concurrent-admin",
        bootstrap_admin_password="strong-test-password",
    )
    await ensure_bootstrap_admin(Factory(), settings)  # type: ignore[arg-type]

    fake_session.add.assert_called_once()
    added = fake_session.add.call_args.args[0]
    assert isinstance(added, User)
    assert added.username == "concurrent-admin"
    fake_session.rollback.assert_awaited_once()
