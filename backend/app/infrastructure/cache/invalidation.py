from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.cache.cache import CacheService
from app.infrastructure.cache.redis import get_redis_circuit, get_redis_for_app
from app.infrastructure.db.models import OutboxTask

logger = logging.getLogger(__name__)


def enqueue_catalog_cache_bump(session: AsyncSession, college_id: int | None) -> None:
    """Make catalog invalidation part of the same transaction as the write."""

    if college_id is None:
        return
    session.add(
        OutboxTask(
            task_key=f"cache-bump:college:{college_id}:{uuid4().hex}",
            task_type="CACHE_BUMP",
            aggregate_key=f"college:{college_id}",
            college_id=college_id,
            payload={"scope": f"college:{college_id}"},
            execute_at=datetime.now(UTC).replace(tzinfo=None),
        )
    )


async def sync_catalog_cache_bump(app: object, college_id: int | None) -> bool:
    """Invalidate a college catalog immediately after a committed write.

    The outbox row remains the durable retry path.  This best-effort fast path
    makes normal writes immediately visible while keeping Redis non-
    authoritative: a Redis outage never rolls back a successful MySQL write.
    """

    if college_id is None:
        return True
    cache = CacheService(
        get_redis_for_app(app),
        app.state.settings,  # type: ignore[attr-defined]
        getattr(app.state, "metrics", None),  # type: ignore[attr-defined]
        get_redis_circuit(app),
    )
    try:
        await cache.bump_version(f"college:{college_id}")
    except Exception as exc:  # Redis is an optimization; the outbox will retry.
        logger.warning("catalog cache invalidation deferred for college %s: %s", college_id, exc)
        return False
    return True
