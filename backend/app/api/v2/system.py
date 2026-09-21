import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select, text, update
from sqlalchemy.exc import SQLAlchemyError

from app.auth.security import Principal, get_current_principal
from app.common.response import ApiResponse
from app.core.errors import ApiError
from app.core.settings import Settings
from app.infrastructure.cache.redis import get_redis, get_redis_circuit, redis_call
from app.infrastructure.db.models import OutboxTask
from app.infrastructure.db.session import build_engine

router = APIRouter()


class HealthData(BaseModel):
    service: str
    version: str
    environment: str
    checks: dict[str, str]


def _health_data(settings: Settings) -> HealthData:
    return HealthData(
        service=settings.app_name,
        version=settings.api_version,
        environment=settings.environment,
        checks={"configuration": "ok"},
    )


@router.get("/live", response_model=ApiResponse[HealthData])
async def live(request: Request) -> ApiResponse[HealthData]:
    settings: Settings = request.app.state.settings
    return ApiResponse.ok(_health_data(settings), request.state.request_id)


@router.get("/metrics", response_class=PlainTextResponse, include_in_schema=False)
async def metrics(request: Request) -> PlainTextResponse:
    registry = getattr(request.app.state, "metrics", None)
    return PlainTextResponse(registry.render_prometheus() if registry is not None else "")


def _require_system_admin(principal: Principal) -> None:
    if not principal.is_system_admin:
        raise ApiError("FORBIDDEN", "只有系统管理员可以管理任务", 403)


@router.get("/system/outbox/failed", response_model=ApiResponse[list[dict[str, object]]])
async def failed_outbox_tasks(
    request: Request,
    principal: Principal = Depends(get_current_principal),
) -> ApiResponse[list[dict[str, object]]]:
    _require_system_admin(principal)
    factory = request.app.state.session_factory
    async with factory() as session:
        rows = list(
            (
                await session.scalars(
                    select(OutboxTask)
                    .where(OutboxTask.status == "FAILED")
                    .order_by(OutboxTask.id.desc())
                    .limit(100)
                )
            ).all()
        )
    return ApiResponse.ok(
        [
            {
                "id": row.id,
                "task_key": row.task_key,
                "task_type": row.task_type,
                "aggregate_key": row.aggregate_key,
                "attempts": row.attempts,
                "last_error": row.last_error,
                "execute_at": row.execute_at,
            }
            for row in rows
        ]
    )


@router.post("/system/outbox/{task_id}/retry", response_model=ApiResponse[dict[str, object]])
async def retry_outbox_task(
    task_id: int,
    request: Request,
    principal: Principal = Depends(get_current_principal),
) -> ApiResponse[dict[str, object]]:
    _require_system_admin(principal)
    factory = request.app.state.session_factory
    async with factory() as session:
        result = await session.execute(
            update(OutboxTask)
            .where(OutboxTask.id == task_id, OutboxTask.status == "FAILED")
            .values(
                status="PENDING",
                attempts=0,
                execute_at=datetime.now(UTC).replace(tzinfo=None),
                claimed_at=None,
                completed_at=None,
                last_error=None,
            )
        )
        if result.rowcount != 1:
            raise ApiError("OUTBOX_NOT_FOUND", "失败任务不存在或已被重新处理", 404)
        await session.commit()
    return ApiResponse.ok({"task_id": task_id, "status": "PENDING"})


@router.get("/ready", response_model=ApiResponse[HealthData])
async def ready(request: Request) -> ApiResponse[HealthData]:
    """Check the durable dependency before accepting traffic.

    Tests intentionally use the lightweight configuration-only path. Redis is
    reported as degraded rather than making the API unavailable because the
    reservation lock is best-effort and the database uniqueness constraint is
    authoritative.
    """
    settings: Settings = request.app.state.settings
    if settings.environment == "test":
        return ApiResponse.ok(_health_data(settings), request.state.request_id)
    checks = {"configuration": "ok", "database": "ok", "redis": "ok"}
    engine = getattr(request.app.state, "db_engine", None)
    if engine is None:
        engine = build_engine(settings)
        request.app.state.db_engine = engine
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as exc:
        checks["database"] = "failed"
        raise ApiError("NOT_READY", "数据库暂不可用", 503, data={"checks": checks}) from exc
    try:

        async def ping_redis():
            return await asyncio.wait_for(get_redis(request).ping(), timeout=0.5)

        await redis_call(get_redis_circuit(request.app), ping_redis)
    except Exception:  # Redis is deliberately non-authoritative for readiness.
        checks["redis"] = "degraded"
    return ApiResponse.ok(
        HealthData(
            service=settings.app_name,
            version=settings.api_version,
            environment=settings.environment,
            checks=checks,
        ),
        request.state.request_id,
    )
