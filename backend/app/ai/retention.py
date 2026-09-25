from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, exists, select

from app.infrastructure.db.models import (
    AiCheckpoint,
    AiCheckpointWrite,
    AiConfirmation,
    AiConversation,
    AiMessage,
    AiRun,
    AiRunEvent,
    AiUsageEvent,
    OutboxTask,
)

logger = logging.getLogger(__name__)
RETENTION_BATCH_SIZE = 100
RETENTION_INTERVAL_SECONDS = 24 * 60 * 60


async def purge_expired_conversations(
    session_factory: Any,
    retention_days: int,
    *,
    batch_size: int = RETENTION_BATCH_SIZE,
    now: datetime | None = None,
) -> int:
    """Delete expired AI conversation data in bounded, retry-safe batches."""
    current = now or datetime.now(UTC).replace(tzinfo=None)
    cutoff = current - timedelta(days=retention_days)
    removed = 0

    for _ in range(batch_size):
        async with session_factory() as session, session.begin():
            conversation = await session.scalar(
                select(AiConversation)
                .where(AiConversation.updated_at < cutoff)
                .where(
                    ~exists(
                        select(AiRun.id).where(
                            AiRun.conversation_id == AiConversation.id,
                            AiRun.status.in_(("QUEUED", "RUNNING")),
                        )
                    )
                )
                .where(
                    ~exists(
                        select(AiConfirmation.id).where(
                            AiConfirmation.conversation_id == AiConversation.id,
                            AiConfirmation.status == "PENDING",
                            AiConfirmation.expires_at > current,
                        )
                    )
                )
                .order_by(AiConversation.updated_at, AiConversation.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if conversation is None:
                break

            runs = list(
                (
                    await session.scalars(
                        select(AiRun.id).where(AiRun.conversation_id == conversation.id)
                    )
                ).all()
            )
            if runs:
                thread_ids = [f"{conversation.graph_thread_id}:{run_id}" for run_id in runs]
                await session.execute(
                    delete(AiCheckpointWrite).where(AiCheckpointWrite.thread_id.in_(thread_ids))
                )
                await session.execute(
                    delete(AiCheckpoint).where(AiCheckpoint.thread_id.in_(thread_ids))
                )
                await session.execute(delete(AiRunEvent).where(AiRunEvent.run_id.in_(runs)))
                await session.execute(delete(AiUsageEvent).where(AiUsageEvent.run_id.in_(runs)))
                await session.execute(delete(AiConfirmation).where(AiConfirmation.run_id.in_(runs)))
                await session.execute(delete(AiRun).where(AiRun.id.in_(runs)))
                await session.execute(
                    delete(OutboxTask).where(
                        OutboxTask.task_key.in_([f"ai-run:{run_id}" for run_id in runs])
                    )
                )
            await session.execute(
                delete(AiConfirmation).where(AiConfirmation.conversation_id == conversation.id)
            )
            await session.execute(
                delete(AiMessage).where(AiMessage.conversation_id == conversation.id)
            )
            await session.delete(conversation)
            removed += 1
    return removed


async def ai_retention_loop(app) -> None:
    """Run at startup and then daily; failures are retried on the next cycle."""
    while True:
        try:
            factory = getattr(app.state, "session_factory", None)
            if factory is not None:
                await purge_expired_conversations(
                    factory,
                    app.state.settings.ai_message_retention_days,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("AI conversation retention sweep failed (%s)", type(exc).__name__)
        await asyncio.sleep(RETENTION_INTERVAL_SECONDS)
