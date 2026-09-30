from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.settings import Settings


def build_engine(settings: Settings) -> AsyncEngine:
    options: dict[str, object] = {
        "echo": settings.debug,
        "pool_pre_ping": True,
    }
    if not settings.mysql_dsn.startswith("sqlite"):
        options.update(
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_recycle=settings.db_pool_recycle_seconds,
            pool_timeout=settings.db_pool_timeout_seconds,
        )
    return create_async_engine(settings.mysql_dsn, **options)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        engine = getattr(request.app.state, "db_engine", None)
        if engine is None:
            engine = build_engine(request.app.state.settings)
            request.app.state.db_engine = engine
        metrics = getattr(request.app.state, "metrics", None)
        if metrics is not None:
            metrics.monitor_sqlalchemy_pool(engine)
        session_factory = build_session_factory(engine)
        request.app.state.session_factory = session_factory

    async with session_factory() as session:
        yield session


async def dispose_app_engine(app: object) -> None:
    state = getattr(app, "state", None)
    engine = getattr(state, "db_engine", None)
    if engine is not None:
        await engine.dispose()
