from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from app.auth.csrf import enforce_csrf
from app.auth.security import Principal, get_current_principal
from app.core.errors import ApiError
from app.core.metrics import MetricsRegistry
from app.core.settings import Settings
from app.infrastructure.db.models import OutboxTask
from app.main import create_app
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _principal(user_id: int, role: str) -> Principal:
    return Principal(
        user_id=user_id,
        username=f"{role.lower()}-{user_id}",
        college_id=1,
        roles=(role,),
        token_type="access",
        token_id=f"system-test-{user_id}",
        permissions=("user:manage",),
    )


@asynccontextmanager
async def _client(
    session_factory: async_sessionmaker[AsyncSession],
    actor: dict[str, Principal],
    *,
    settings: Settings | None = None,
) -> AsyncIterator[AsyncClient]:
    app = create_app(
        settings
        or Settings(
            environment="test",
            cors_origins=["http://test"],
            redis_url="redis://127.0.0.1:6379/15",
        )
    )
    app.state.session_factory = session_factory

    async def override_actor() -> Principal:
        return actor["value"]

    async def no_csrf() -> None:
        return None

    app.dependency_overrides[get_current_principal] = override_actor
    app.dependency_overrides[enforce_csrf] = no_csrf
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_system_live_metrics_and_outbox_retry_authorization(seeded) -> None:
    factory, _college, _other_college, student, _other_student, _manager, *_ = seeded
    execute_at = datetime.now(UTC).replace(tzinfo=None)
    async with factory() as session:
        failed = OutboxTask(
            task_key="system-test-failed-task-0001",
            task_type="NOTIFICATION",
            aggregate_key="reservation:1",
            college_id=1,
            payload={"user_id": student.id, "type": "RESERVATION_UPDATE"},
            status="FAILED",
            attempts=4,
            execute_at=execute_at,
            last_error="temporary downstream failure",
        )
        pending = OutboxTask(
            task_key="system-test-pending-task-0001",
            task_type="NOTIFICATION",
            aggregate_key="reservation:2",
            college_id=1,
            payload={"user_id": student.id, "type": "RESERVATION_UPDATE"},
            status="PENDING",
            attempts=0,
            execute_at=execute_at,
        )
        session.add_all([failed, pending])
        await session.commit()
        failed_id = failed.id
        pending_id = pending.id

    token = "system-metrics-test-token-000000000000"
    actor = {"value": _principal(student.id, "STUDENT")}
    settings = Settings(
        environment="test",
        cors_origins=["http://test"],
        redis_url="redis://127.0.0.1:6379/15",
        metrics_token=token,
    )
    async with _client(factory, actor, settings=settings) as client:
        live = await client.get("/api/v2/live")
        assert live.status_code == 200
        assert live.json()["data"] == {"status": "ok"}

        disabled_metrics = await client.get("/api/v2/metrics")
        assert disabled_metrics.status_code == 401

        forbidden_tasks = await client.get("/api/v2/system/outbox/failed")
        assert forbidden_tasks.status_code == 403
        forbidden_retry = await client.post(f"/api/v2/system/outbox/{failed_id}/retry")
        assert forbidden_retry.status_code == 403

        actor["value"] = _principal(student.id, "SYS_ADMIN")
        test_ready = await client.get("/api/v2/ready")
        assert test_ready.status_code == 200
        assert test_ready.json()["data"]["checks"] == {"configuration": "ok"}
        metrics = await client.get("/api/v2/metrics", headers={"Authorization": f"Bearer {token}"})
        assert metrics.status_code == 200
        assert metrics.headers["content-type"].startswith("text/plain")

        failed_list = await client.get("/api/v2/system/outbox/failed")
        assert failed_list.status_code == 200
        assert [row["id"] for row in failed_list.json()["data"]] == [failed_id]
        assert failed_list.json()["data"][0]["attempts"] == 4

        retried = await client.post(f"/api/v2/system/outbox/{failed_id}/retry")
        assert retried.status_code == 200
        assert retried.json()["data"] == {"task_id": failed_id, "status": "PENDING"}
        missing = await client.post(f"/api/v2/system/outbox/{failed_id}/retry")
        assert missing.status_code == 404
        non_failed = await client.post(f"/api/v2/system/outbox/{pending_id}/retry")
        assert non_failed.status_code == 404

    async with factory() as session:
        stored = await session.get(OutboxTask, failed_id)
        assert stored is not None
        assert stored.status == "PENDING"
        assert stored.attempts == 0
        assert stored.last_error is None
        assert stored.claimed_at is None
        assert stored.completed_at is None


class _Connection:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def execute(self, _statement: object) -> None:
        if self.error is not None:
            raise self.error


class _ConnectionContext:
    def __init__(self, error: Exception | None = None) -> None:
        self.connection = _Connection(error)

    async def __aenter__(self) -> _Connection:
        return self.connection

    async def __aexit__(self, *_args: object) -> None:
        return None


class _Engine:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def connect(self) -> _ConnectionContext:
        return _ConnectionContext(self.error)


@pytest.mark.asyncio
@pytest.mark.parametrize("database_error", [None, OSError("database offline")])
@pytest.mark.parametrize("redis_error", [None, RuntimeError("redis offline")])
async def test_readiness_reports_database_failure_and_redis_degradation(
    seeded,
    monkeypatch: pytest.MonkeyPatch,
    database_error: Exception | None,
    redis_error: Exception | None,
) -> None:
    from app.api.v2 import system as system_api

    factory, _college, _other_college, student, *_ = seeded
    actor = {"value": _principal(student.id, "SYS_ADMIN")}
    engine = _Engine(database_error)

    class _Redis:
        async def ping(self) -> bool:
            if redis_error is not None:
                raise redis_error
            return True

    monkeypatch.setattr(system_api, "build_engine", lambda _settings: engine)
    monkeypatch.setattr(system_api, "get_redis", lambda _request: _Redis())
    monkeypatch.setattr(
        system_api,
        "get_redis_circuit",
        lambda _app: SimpleNamespace(allow=lambda: True, record_success=lambda: None),
    )
    monkeypatch.setattr(
        MetricsRegistry,
        "monitor_sqlalchemy_pool",
        lambda _self, _engine: None,
    )
    settings = Settings(
        environment="dev",
        cors_origins=["http://test"],
        redis_url="redis://127.0.0.1:6379/15",
    )
    async with _client(factory, actor, settings=settings) as client:
        response = await client.get("/api/v2/ready")
        reused_engine = await client.get("/api/v2/ready")

    assert reused_engine.status_code == response.status_code

    if database_error is not None:
        assert response.status_code == 503
        assert response.json()["code"] == "NOT_READY"
        assert response.json()["data"]["checks"]["database"] == "failed"
    else:
        assert response.status_code == 200
        assert response.json()["data"]["checks"]["database"] == "ok"
        assert response.json()["data"]["checks"]["redis"] == (
            "degraded" if redis_error is not None else "ok"
        )


@pytest.mark.asyncio
async def test_metrics_returns_empty_body_when_registry_is_not_initialized() -> None:
    from app.api.v2.system import metrics
    from starlette.requests import Request

    token = "empty-registry-metrics-token-000000000"
    request = Request(
        {
            "type": "http",
            "app": SimpleNamespace(
                state=SimpleNamespace(
                    settings=Settings(environment="test", cors_origins=[], metrics_token=token),
                    metrics=None,
                )
            ),
            "headers": [],
            "method": "GET",
            "path": "/api/v2/metrics",
        }
    )

    response = await metrics(request, authorization=f"Bearer {token}")

    assert response.body == b""

    disabled_request = Request(
        {
            "type": "http",
            "app": SimpleNamespace(
                state=SimpleNamespace(
                    settings=Settings(environment="test", cors_origins=[], metrics_token=""),
                    metrics=None,
                )
            ),
            "headers": [],
            "method": "GET",
            "path": "/api/v2/metrics",
        }
    )
    with pytest.raises(ApiError) as error:
        await metrics(disabled_request, authorization=None)
    assert error.value.status_code == 404
