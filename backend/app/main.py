from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v2.router import router as v2_router
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
from app.infrastructure.db.session import dispose_app_engine


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
    return app


app = create_app()
