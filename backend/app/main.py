import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v2.router import router as v2_router
from app.auth.security import Principal, decode_token
from app.core.admission import RequestCapacityMiddleware
from app.core.client_ip import resolve_client_ip
from app.core.errors import (
    ApiError,
    api_error_handler,
    http_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from app.core.metrics import MetricsRegistry
from app.core.request_id import RequestIdMiddleware
from app.core.settings import Settings, get_settings
from app.infrastructure.cache.redis import dispose_app_redis
from app.infrastructure.db.models import RefreshSession, User
from app.infrastructure.db.session import dispose_app_engine
from app.infrastructure.notifications.realtime import NotificationHub


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker = None
    upload_cleanup_task = None
    ai_retention_task = None
    if app.state.settings.environment != "test":
        from app.infrastructure.db.bootstrap import ensure_bootstrap_admin
        from app.infrastructure.db.operational_bootstrap import ensure_operational_metadata
        from app.infrastructure.db.session import build_engine, build_session_factory

        engine = getattr(app.state, "db_engine", None)
        if engine is None:
            engine = build_engine(app.state.settings)
            app.state.db_engine = engine
        factory = getattr(app.state, "session_factory", None)
        if factory is None:
            factory = build_session_factory(engine)
            app.state.session_factory = factory
        await ensure_bootstrap_admin(factory, app.state.settings)
        await ensure_operational_metadata(factory, app.state.settings)
    if app.state.settings.enable_workers and app.state.settings.environment != "test":
        from app.ai.retention import ai_retention_loop
        from app.core.uploads import upload_cleanup_loop
        from app.infrastructure.tasks.worker import OutboxWorker

        worker = OutboxWorker(app)
        await worker.start()
        upload_cleanup_task = asyncio.create_task(
            upload_cleanup_loop(app),
            name="upload-orphan-cleanup",
        )
        ai_retention_task = asyncio.create_task(
            ai_retention_loop(app),
            name="ai-conversation-retention",
        )
    try:
        yield
    finally:
        if upload_cleanup_task is not None:
            upload_cleanup_task.cancel()
            await asyncio.gather(upload_cleanup_task, return_exceptions=True)
        if ai_retention_task is not None:
            ai_retention_task.cancel()
            await asyncio.gather(ai_retention_task, return_exceptions=True)
        if worker is not None:
            await worker.stop()
        await dispose_app_engine(app)
        await dispose_app_redis(app)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.api_version,
        debug=resolved_settings.debug,
        lifespan=lifespan,
        docs_url=f"{resolved_settings.api_prefix}/docs",
        redoc_url=f"{resolved_settings.api_prefix}/redoc",
        openapi_url=f"{resolved_settings.api_prefix}/openapi.json",
    )
    app.state.settings = resolved_settings
    app.state.metrics = MetricsRegistry()
    app.state.notification_hub = NotificationHub()
    app.add_middleware(
        RequestCapacityMiddleware,
        capacity=resolved_settings.db_pool_size + resolved_settings.db_max_overflow,
        exempt_paths={f"{resolved_settings.api_prefix}/live"},
        exempt_capacity=resolved_settings.request_health_capacity,
    )
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
        expose_headers=["X-AI-Run-ID"],
    )
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
    app.include_router(v2_router, prefix=resolved_settings.api_prefix)

    @app.websocket(f"{resolved_settings.api_prefix}/ws")
    async def notification_websocket(websocket: WebSocket) -> None:
        hub: NotificationHub = app.state.notification_hub
        peer = websocket.client.host if websocket.client else None
        client_ip = resolve_client_ip(
            peer,
            websocket.headers.get("x-forwarded-for"),
            resolved_settings.trusted_proxy_ips,
        )
        if not await hub.reserve_pending(
            websocket,
            client_ip,
            max_pending=resolved_settings.websocket_max_pending,
            max_per_ip=resolved_settings.websocket_max_pending_per_ip,
        ):
            await websocket.close(code=1013)
            return
        connected_user_id: int | None = None
        try:
            # Authenticate in the first frame so credentials never appear in
            # query strings, browser history, or reverse-proxy access logs.
            await websocket.accept()
            auth_frame = await asyncio.wait_for(
                websocket.receive_text(),
                timeout=resolved_settings.websocket_auth_timeout_seconds,
            )
            if len(auth_frame) > 2048:
                await websocket.close(code=4401)
                return
            try:
                auth_payload = json.loads(auth_frame)
            except (json.JSONDecodeError, TypeError):
                await websocket.close(code=4401)
                return
            token = auth_payload.get("token") if isinstance(auth_payload, dict) else None
            if (
                not isinstance(auth_payload, dict)
                or auth_payload.get("type") != "auth"
                or not isinstance(token, str)
                or not token
            ):
                await websocket.close(code=4401)
                return
            token_principal = decode_token(websocket, token)
            factory = getattr(app.state, "session_factory", None)
            if factory is None:
                await websocket.close(code=1013)
                return
            async with factory() as session:
                active_session = await session.scalar(
                    select(RefreshSession.id).where(
                        RefreshSession.family_id == token_principal.session_id,
                        RefreshSession.user_id == token_principal.user_id,
                        RefreshSession.revoked_at.is_(None),
                        RefreshSession.expires_at > datetime.now(UTC).replace(tzinfo=None),
                    )
                )
                if active_session is None:
                    await websocket.close(code=4401)
                    return
                user = await session.scalar(
                    select(User)
                    .options(selectinload(User.roles))
                    .where(User.id == token_principal.user_id, User.status == 1)
                )
            if user is None:
                await websocket.close(code=4401)
                return
            # Rebuild the principal from current database state. A disabled
            # user or a role/college change must take effect for WS delivery
            # without waiting for an old access token to expire.
            principal = Principal(
                user_id=user.id,
                username=user.username,
                college_id=user.college_id,
                roles=tuple(role.role_code for role in user.roles),
                token_type=token_principal.token_type,
                token_id=token_principal.token_id,
                session_id=token_principal.session_id,
            )
            if not await hub.connect(
                principal.user_id,
                websocket,
                max_total=resolved_settings.websocket_max_connections,
                max_per_user=resolved_settings.websocket_max_per_user,
                session_id=principal.session_id,
            ):
                await websocket.close(code=1013)
                return
            connected_user_id = principal.user_id
            while True:
                # The client sends small keep-alive messages. Notifications
                # are pushed by OutboxWorker; history is always HTTP-backed.
                await websocket.receive_text()
        except ApiError:
            await websocket.close(code=4401)
        except TimeoutError:
            await websocket.close(code=4408)
        except WebSocketDisconnect:
            pass
        finally:
            if connected_user_id is not None:
                await hub.disconnect(connected_user_id, websocket)
            else:
                await hub.disconnect_pending(websocket)

    return app


app = create_app()
