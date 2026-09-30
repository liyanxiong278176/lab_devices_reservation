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
    AiContextSnapshot,
    AiConversation,
    AiMemory,
    AiMessage,
    AiRun,
    AiRunEvent,
    AiToolExecution,
    AiUsageEvent,
    OutboxTask,
)

logger = logging.getLogger(__name__)
RETENTION_BATCH_SIZE = 100
RETENTION_INTERVAL_SECONDS = 24 * 60 * 60
MEMORY_ARCHIVE_GRACE_DAYS = 180


async def _delete_run_artifacts(session: Any, conversation: AiConversation, run_id: int) -> None:
    thread_id = f"{conversation.graph_thread_id}:{run_id}"
    await session.execute(
        delete(AiCheckpointWrite).where(AiCheckpointWrite.thread_id == thread_id)
    )
    await session.execute(delete(AiCheckpoint).where(AiCheckpoint.thread_id == thread_id))
    await session.execute(delete(AiRunEvent).where(AiRunEvent.run_id == run_id))
    await session.execute(delete(AiUsageEvent).where(AiUsageEvent.run_id == run_id))
    await session.execute(delete(AiToolExecution).where(AiToolExecution.run_id == run_id))
    await session.execute(delete(AiConfirmation).where(AiConfirmation.run_id == run_id))
    await session.execute(delete(OutboxTask).where(OutboxTask.task_key == f"ai-run:{run_id}"))
    await session.execute(delete(AiRun).where(AiRun.id == run_id))


async def sweep_ai_retention(
    session_factory: Any,
    retention_days: int = 180,
    *,
    batch_size: int = RETENTION_BATCH_SIZE,
    now: datetime | None = None,
) -> dict[str, int]:
    """Archive expired L0/L1/L2 data first, then erase it after 180 unused days."""
    current = now or datetime.now(UTC).replace(tzinfo=None)
    message_cutoff = current - timedelta(days=retention_days)
    archive_purge_cutoff = current - timedelta(days=MEMORY_ARCHIVE_GRACE_DAYS)
    archived_messages = archived_memories = purged_messages = purged_memories = 0

    async with session_factory() as session, session.begin():
        message_query = (
            select(AiMessage)
            .where(
                AiMessage.archived_at.is_(None),
                AiMessage.expires_at <= current,
                AiMessage.created_at <= message_cutoff,
                ~exists(
                    select(AiRun.id).where(
                        AiRun.conversation_id == AiMessage.conversation_id,
                        AiRun.status.in_(("QUEUED", "RUNNING")),
                    )
                ),
                ~exists(
                    select(AiConfirmation.id).where(
                        AiConfirmation.conversation_id == AiMessage.conversation_id,
                        AiConfirmation.status == "PENDING",
                        AiConfirmation.expires_at > current,
                    )
                ),
            )
            .order_by(AiMessage.expires_at, AiMessage.id)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        expired_messages = list((await session.scalars(message_query)).all())
        for message in expired_messages:
            message.archived_at = current
            # Snapshots are derived from raw conversation messages. Drop the
            # affected conversation summary so an archived message cannot
            # remain available through compressed context.
            await session.execute(
                delete(AiContextSnapshot).where(
                    AiContextSnapshot.conversation_id == message.conversation_id
                )
            )
            archived_messages += 1

        memory_query = (
            select(AiMemory)
            .where(AiMemory.status == "ACTIVE", AiMemory.expires_at <= current)
            .order_by(AiMemory.expires_at, AiMemory.id)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        expired_memories = list((await session.scalars(memory_query)).all())
        for memory in expired_memories:
            memory.status = "ARCHIVED"
            memory.archived_at = current
            memory.updated_at = current
            archived_memories += 1

    async with session_factory() as session, session.begin():
        old_memory_query = (
            select(AiMemory)
            .where(
                AiMemory.status == "ARCHIVED",
                AiMemory.archived_at <= archive_purge_cutoff,
                (
                    AiMemory.last_recalled_at.is_(None)
                    | (AiMemory.last_recalled_at <= AiMemory.archived_at)
                ),
            )
            .order_by(AiMemory.archived_at, AiMemory.id)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        old_memories = list((await session.scalars(old_memory_query)).all())
        for memory in old_memories:
            await session.delete(memory)
            purged_memories += 1

        old_messages_query = (
            select(AiMessage)
            .where(
                AiMessage.archived_at <= archive_purge_cutoff,
                ~exists(
                    select(AiRun.id).where(
                        AiRun.conversation_id == AiMessage.conversation_id,
                        AiRun.status.in_(("QUEUED", "RUNNING")),
                    )
                ),
                ~exists(
                    select(AiConfirmation.id).where(
                        AiConfirmation.conversation_id == AiMessage.conversation_id,
                        AiConfirmation.status == "PENDING",
                        AiConfirmation.expires_at > current,
                    )
                ),
            )
            .order_by(AiMessage.archived_at, AiMessage.id)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        old_messages = list((await session.scalars(old_messages_query)).all())
        for message in old_messages:
            metadata = message.metadata_json if isinstance(message.metadata_json, dict) else {}
            run_id = metadata.get("run_id")
            run_key = metadata.get("run_key")
            run = None
            if isinstance(run_id, int):
                run = await session.scalar(select(AiRun).where(AiRun.id == run_id))
            elif isinstance(run_key, str):
                run = await session.scalar(select(AiRun).where(AiRun.run_key == run_key))
            if run is not None:
                conversation = await session.get(AiConversation, message.conversation_id)
                if conversation is not None:
                    await _delete_run_artifacts(session, conversation, run.id)
            await session.delete(message)
            purged_messages += 1

    return {
        "archived_messages": archived_messages,
        "archived_memories": archived_memories,
        "purged_messages": purged_messages,
        "purged_memories": purged_memories,
    }


async def purge_expired_conversations(
    session_factory: Any,
    retention_days: int,
    *,
    batch_size: int = RETENTION_BATCH_SIZE,
    now: datetime | None = None,
) -> int:
    """Backward-compatible wrapper; conversation rows are no longer deleted by TTL."""
    result = await sweep_ai_retention(
        session_factory,
        retention_days,
        batch_size=batch_size,
        now=now,
    )
    return sum(result.values())


async def ai_retention_loop(app) -> None:
    """Run at startup and then daily; failures are retried on the next cycle."""
    while True:
        try:
            factory = getattr(app.state, "session_factory", None)
            if factory is not None:
                await sweep_ai_retention(
                    factory,
                    app.state.settings.ai_message_retention_days,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("AI retention sweep failed (%s)", type(exc).__name__)
        await asyncio.sleep(RETENTION_INTERVAL_SECONDS)
