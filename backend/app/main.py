from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v2.router import router as v2_router
from app.auth.security import Principal, decode_token
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
from app.infrastructure.db.models import User
from app.infrastructure.db.session import dispose_app_engine
from app.infrastructure.notifications.realtime import NotificationHub


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker = None
    if app.state.settings.environment != "test":
        from app.infrastructure.db.bootstrap import ensure_bootstrap_admin
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
    if app.state.settings.enable_workers and app.state.settings.environment != "test":
        from app.infrastructure.tasks.worker import OutboxWorker

        worker = OutboxWorker(app)
        await worker.start()
    try:
        yield
    finally:
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
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
    )
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
    app.include_router(v2_router, prefix=resolved_settings.api_prefix)

    @app.websocket(f"{resolved_settings.api_prefix}/ws")
    async def notification_websocket(websocket: WebSocket) -> None:
        token = websocket.query_params.get("token")
        if not token:
            await websocket.close(code=4401)
            return
        try:
            token_principal = decode_token(websocket, token)
            factory = getattr(app.state, "session_factory", None)
            if factory is None:
                await websocket.close(code=1013)
                return
            async with factory() as session:
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
            )
        except ApiError:
            await websocket.close(code=4401)
            return
        hub: NotificationHub = app.state.notification_hub
        await hub.connect(principal.user_id, websocket)
        try:
            while True:
                # The client sends small keep-alive messages.  Notifications
                # are pushed by OutboxWorker; history is always HTTP-backed.
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            await hub.disconnect(principal.user_id, websocket)

    return app


app = create_app()
