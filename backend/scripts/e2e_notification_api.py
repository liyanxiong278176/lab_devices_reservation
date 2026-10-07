"""Uvicorn entry point with opt-in, test-only notification fault injection.

This module is intentionally not used by the application or deployment files.
The explicit environment flag and local Redis DB guard prevent accidental use
outside the isolated notification E2E run.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping

from app.core.settings import Settings
from app.infrastructure.notifications.realtime import NotificationHub
from app.infrastructure.notifications.relay import RedisNotificationRelay
from sqlalchemy.engine import make_url

settings = Settings()
redis_url = make_url(settings.redis_url)
if (
    os.environ.get("E2E_NOTIFICATION_CHAOS") != "1"
    or settings.environment not in {"local", "test"}
    or redis_url.host != "127.0.0.1"
    or redis_url.port != 6379
    or redis_url.database != "14"
):
    raise RuntimeError("test API requires explicit chaos opt-in and isolated local Redis DB 14")


_original_hub_publish = NotificationHub.publish
_original_process_message = RedisNotificationRelay._process_message


async def _publish_with_test_failure(
    hub: NotificationHub,
    user_id: int,
    payload: dict[str, object],
) -> int:
    if str(payload.get("title", "")).startswith("E2E_HUB_FAIL:"):
        raise RuntimeError("injected E2E SSE Hub handoff failure")
    return await _original_hub_publish(hub, user_id, payload)


def _field(fields: Mapping[object, object], key: str) -> str:
    value = fields.get(key, fields.get(key.encode(), ""))
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)


async def _hold_test_backlog(
    relay: RedisNotificationRelay,
    message_id: str,
    fields: dict[object, object],
    attempt: int,
) -> None:
    source = _field(fields, "source_task_key")
    prefix = os.environ.get("E2E_NOTIFICATION_PREFIX", "")
    if prefix and source.startswith(f"e2e-backlog:{prefix}:"):
        hold_key = f"e2e:notification:{prefix}:backlog-hold"
        while await relay._consumer.exists(hold_key):
            await asyncio.sleep(0.25)
    await _original_process_message(relay, message_id, fields, attempt)


NotificationHub.publish = _publish_with_test_failure  # type: ignore[method-assign]
RedisNotificationRelay._process_message = _hold_test_backlog  # type: ignore[method-assign]

from app.main import app  # noqa: E402,F401  (patch classes before app/lifespan creation)
