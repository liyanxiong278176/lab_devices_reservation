import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v2.router import router as v2_router
from app.core.admission import RequestCapacityMiddleware
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
from app.infrastructure.cache.redis import dispose_app_redis, get_redis_for_app
from app.infrastructure.db.session import dispose_app_engine
from app.infrastructure.notifications.realtime import NotificationHub
from app.infrastructure.notifications.relay import RedisNotificationRelay

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker = None
    notification_relay = None
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
        app.state.metrics.monitor_sqlalchemy_pool(engine)
        factory = getattr(app.state, "session_factory", None)
        if factory is None:
            factory = build_session_factory(engine)
            app.state.session_factory = factory
        await ensure_bootstrap_admin(factory, app.state.settings)
        await ensure_operational_metadata(factory, app.state.settings)
        notification_relay = RedisNotificationRelay(
            app.state.notification_hub,
            get_redis_for_app(app),
            app.state.settings.redis_url,
            socket_connect_timeout=app.state.settings.redis_socket_timeout_seconds,
        )
        app.state.notification_relay = notification_relay
        await notification_relay.start()
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
        if notification_relay is not None:
            await notification_relay.stop()
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
        queue_capacity=resolved_settings.request_queue_capacity,
        exempt_paths={f"{resolved_settings.api_prefix}/live"},
        bypass_paths={f"{resolved_settings.api_prefix}/notifications/stream"},
        exempt_capacity=resolved_settings.request_health_capacity,
    )
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Content-Type",
            "Idempotency-Key",
            "X-Request-ID",
            "X-CSRF-Token",
        ],
        expose_headers=["X-AI-Run-ID"],
    )
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
    app.include_router(v2_router, prefix=resolved_settings.api_prefix)

    return app


app = create_app()
