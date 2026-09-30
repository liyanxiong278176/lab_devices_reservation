from datetime import datetime, timedelta

import pytest
from app.ai.retention import sweep_ai_retention
from app.infrastructure.db.models import AiConversation, AiMemory, AiMessage
from sqlalchemy import select


@pytest.mark.asyncio
async def test_retention_archives_expired_data_before_purging(seeded) -> None:
    factory, college, _, user, *_ = seeded
    now = datetime(2026, 9, 24, 12)

    async with factory() as session:
        conversation = AiConversation(
            user_id=user.id,
            college_id=college.id,
            title="历史对话",
            graph_thread_id="retention-expired",
        )
        session.add(conversation)
        await session.flush()
        message = AiMessage(
            conversation_id=conversation.id,
            user_id=user.id,
            college_id=college.id,
            role="user",
            content="历史原始消息",
            created_at=now - timedelta(days=181),
            expires_at=now - timedelta(days=1),
        )
        memory = AiMemory(
            user_id=user.id,
            college_id=college.id,
            level="L1",
            scenario="general",
            content="历史事实记忆",
            source_message_ids=[],
            source_run_ids=[],
            status="ACTIVE",
            expires_at=now - timedelta(days=1),
        )
        session.add_all([message, memory])
        await session.commit()
        message_id, memory_id, conversation_id = message.id, memory.id, conversation.id

    first = await sweep_ai_retention(factory, now=now)
    async with factory() as session:
        archived_message = await session.get(AiMessage, message_id)
        archived_memory = await session.get(AiMemory, memory_id)
        conversation_kept = await session.get(AiConversation, conversation_id)

    assert first["archived_messages"] == 1
    assert first["archived_memories"] == 1
    assert archived_message is not None and archived_message.archived_at == now
    assert archived_memory is not None and archived_memory.status == "ARCHIVED"
    assert conversation_kept is not None

    old_archive = now - timedelta(days=181)
    async with factory() as session:
        archived_message = await session.get(AiMessage, message_id)
        archived_memory = await session.get(AiMemory, memory_id)
        assert archived_message and archived_memory
        archived_message.archived_at = old_archive
        archived_memory.archived_at = old_archive
        await session.commit()

    second = await sweep_ai_retention(factory, now=now)
    async with factory() as session:
        assert await session.get(AiMessage, message_id) is None
        assert await session.get(AiMemory, memory_id) is None
        assert await session.get(AiConversation, conversation_id) is not None

    assert second["purged_messages"] == 1
    assert second["purged_memories"] == 1


@pytest.mark.asyncio
async def test_retention_does_not_archive_messages_with_active_run(seeded) -> None:
    factory, college, _, user, *_ = seeded
    now = datetime(2026, 9, 24, 12)
    async with factory() as session:
        conversation = AiConversation(
            user_id=user.id,
            college_id=college.id,
            title="运行中对话",
            graph_thread_id="retention-running",
        )
        session.add(conversation)
        await session.flush()
        message = AiMessage(
            conversation_id=conversation.id,
            user_id=user.id,
            college_id=college.id,
            role="user",
            content="不能归档",
            created_at=now - timedelta(days=181),
            expires_at=now - timedelta(days=1),
        )
        session.add(message)
        await session.flush()
        from app.infrastructure.db.models import AiRun

        session.add(
            AiRun(
                run_key="retention-active-run",
                conversation_id=conversation.id,
                user_id=user.id,
                college_id=college.id,
                status="RUNNING",
                input_text="仍在运行",
            )
        )
        await session.commit()
        message_id = message.id

    result = await sweep_ai_retention(factory, now=now)
    async with factory() as session:
        message = await session.scalar(select(AiMessage).where(AiMessage.id == message_id))
    assert result["archived_messages"] == 0
    assert message is not None and message.archived_at is None
