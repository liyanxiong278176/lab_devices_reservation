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
            # Booking rechecks availability after locking the selected Device
            # row. READ COMMITTED gives that non-locking recheck a fresh view
            # without taking InnoDB next-key locks on empty device/date ranges.
            # The unique (device_id, date) index remains the final guard.
            isolation_level="READ COMMITTED",
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_recycle=settings.db_pool_recycle_seconds,
            pool_timeout=settings.db_pool_timeout_seconds,
        )
    return create_async_engine(settings.mysql_dsn, **options)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
