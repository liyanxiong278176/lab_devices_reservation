from datetime import datetime, timedelta

import pytest
from app.ai.memory import (
    confirm_l2_memory,
    extract_turn_memories,
    find_memories_forget_preview,
    invalidate_memories,
    load_relevant_l0_messages,
    load_relevant_memories,
    memory_ttl_days,
    record_valid_l0_recalls,
    record_valid_recalls,
    reject_l2_memory,
    save_turn_memories,
)
from app.infrastructure.db.models import AiConversation, AiMemory, AiMemoryRecall, AiMessage, AiRun
from sqlalchemy import select


def test_memory_ttl_increases_with_diminishing_returns() -> None:
    assert memory_ttl_days(0) == 180
    assert memory_ttl_days(1) == 240
    assert memory_ttl_days(3) == 300
    assert memory_ttl_days(7) == 360
    assert 240 < memory_ttl_days(2) < 300
    assert memory_ttl_days(1000) == 360


def test_memory_extraction_requires_explicit_language_and_redacts_sensitive_values() -> None:
    candidates = extract_turn_memories("我正在研究电镜图像分析")
    assert len(candidates) == 1 and candidates[0].level == "L1"
    assert extract_turn_memories("今天想预约一台显微镜") == []
    candidates = extract_turn_memories("请记住我偏好 alice@example.edu 的通知方式")
    assert candidates and candidates[0].level == "L2"
    assert "alice@example.edu" not in candidates[0].content


@pytest.mark.asyncio
async def test_memory_is_user_scoped_and_l2_requires_confirmation(seeded) -> None:
    factory, college, other_college, user, other_user, *_ = seeded
    now = datetime(2026, 9, 24, 12)
    async with factory() as session:
        conversation = AiConversation(
            user_id=user.id,
            college_id=college.id,
            title="记忆来源",
            graph_thread_id="memory-source",
        )
        session.add(conversation)
        await session.flush()
        message = AiMessage(
            conversation_id=conversation.id,
            user_id=user.id,
            college_id=college.id,
            role="user",
            content="请记住我偏好先看预约规则，再选择设备",
        )
        session.add(message)
        await session.flush()
        run = AiRun(
            run_key="memory-source-run",
            conversation_id=conversation.id,
            user_id=user.id,
            college_id=college.id,
            status="COMPLETED",
            input_text=message.content,
        )
        session.add(run)
        await session.flush()
        saved = await save_turn_memories(
            session,
            user_id=user.id,
            college_id=college.id,
            run_id=run.id,
            source_message_id=message.id,
            text=message.content,
            now=now,
        )
        l2 = next(memory for memory in saved if memory.level == "L2")
        assert l2.status == "PENDING_CONFIRMATION"
        assert await load_relevant_memories(
            session,
            user_id=other_user.id,
            college_id=other_college.id,
            query="预约规则设备",
            now=now,
        ) == []
        assert await confirm_l2_memory(
            session,
            user_id=other_user.id,
            memory_id=l2.id,
            now=now,
        ) is None
        assert await confirm_l2_memory(
            session,
            user_id=user.id,
            memory_id=l2.id,
            now=now,
        ) is l2
        loaded = await load_relevant_memories(
            session,
            user_id=user.id,
            college_id=college.id,
            query="预约规则设备",
            now=now,
        )
        assert l2 in loaded
        assert await record_valid_recalls(
            session,
            run_id=run.id,
            memories=loaded,
            used_memory_ids=[l2.id],
            now=now,
        ) == 1
        assert await record_valid_recalls(
            session,
            run_id=run.id,
            memories=loaded,
            used_memory_ids=[l2.id],
            now=now + timedelta(minutes=1),
        ) == 0
        await session.flush()
        recall_rows = list(
            (
                await session.scalars(
                    select(AiMemoryRecall).where(AiMemoryRecall.memory_id == l2.id)
                )
            ).all()
        )
        assert len(recall_rows) == 1
        assert l2.recall_count == 1
        assert l2.expires_at == now + timedelta(days=240)
        await session.commit()


@pytest.mark.asyncio
async def test_memory_forget_preview_and_invalidation_are_owner_scoped(seeded) -> None:
    factory, college, other_college, user, other_user, *_ = seeded
    now = datetime(2026, 9, 24, 12)
    async with factory() as session:
        own = AiMemory(
            user_id=user.id,
            college_id=college.id,
            level="L1",
            scenario="reservation",
            content="我负责预约电子显微镜项目",
            source_message_ids=[],
            source_run_ids=[],
            status="ACTIVE",
            expires_at=now + timedelta(days=180),
        )
        foreign = AiMemory(
            user_id=other_user.id,
            college_id=other_college.id,
            level="L1",
            scenario="reservation",
            content="我负责预约光谱仪项目",
            source_message_ids=[],
            source_run_ids=[],
            status="ACTIVE",
            expires_at=now + timedelta(days=180),
        )
        session.add_all([own, foreign])
        await session.flush()
        found = await find_memories_forget_preview(session, user_id=user.id, topic="预约电子显微镜")
        assert [memory.id for memory in found] == [own.id]
        assert await invalidate_memories(session, user_id=other_user.id, memory_ids=[own.id]) == 0
        assert await invalidate_memories(session, user_id=user.id, memory_ids=[own.id]) == 1
        assert own.status == "INVALID"
        assert await reject_l2_memory(session, user_id=user.id, memory_id=own.id) is None


@pytest.mark.asyncio
async def test_archived_l0_recall_restores_ttl_once_per_run(seeded) -> None:
    factory, college, _, user, *_ = seeded
    now = datetime(2026, 9, 24, 12)
    async with factory() as session:
        conversation = AiConversation(
            user_id=user.id,
            college_id=college.id,
            title="L0 归档检索",
            graph_thread_id="memory-l0-recall",
        )
        session.add(conversation)
        await session.flush()
        old_message = AiMessage(
            conversation_id=conversation.id,
            user_id=user.id,
            college_id=college.id,
            role="user",
            content="我之前偏好预约前先查看安全操作规范",
            created_at=now - timedelta(days=182),
            expires_at=now - timedelta(days=2),
            archived_at=now - timedelta(days=1),
        )
        session.add(old_message)
        await session.flush()
        run = AiRun(
            run_key="memory-l0-recall-run",
            conversation_id=conversation.id,
            user_id=user.id,
            college_id=college.id,
            status="COMPLETED",
            input_text="历史预约偏好",
        )
        session.add(run)
        await session.flush()
        matches = await load_relevant_l0_messages(
            session,
            user_id=user.id,
            query="预约前查看安全操作规范",
            now=now,
            include_archived=True,
        )
        assert [item.id for item in matches] == [old_message.id]
        assert await record_valid_l0_recalls(
            session,
            run_id=run.id,
            messages=matches,
            used_message_ids=[old_message.id],
            now=now,
        ) == 1
        assert await record_valid_l0_recalls(
            session,
            run_id=run.id,
            messages=matches,
            used_message_ids=[old_message.id],
            now=now + timedelta(minutes=1),
        ) == 0
        await session.flush()
        assert old_message.archived_at is None
        assert old_message.recall_count == 1
        assert old_message.expires_at == now + timedelta(days=240)
        await session.commit()
