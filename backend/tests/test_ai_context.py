from datetime import datetime, timedelta

import pytest
from app.ai.context import PROTECTED_TURNS, load_conversation_context
from app.infrastructure.db.models import AiContextSnapshot, AiConversation, AiMessage
from sqlalchemy import select


@pytest.mark.asyncio
async def test_context_compresses_and_preserves_recent_turns(seeded) -> None:
    factory, college, _, user, *_ = seeded
    async with factory() as session:
        conversation = AiConversation(
            user_id=user.id,
            college_id=college.id,
            title="上下文测试",
            graph_thread_id="context-protection",
        )
        session.add(conversation)
        await session.flush()
        for turn in range(PROTECTED_TURNS + 1):
            session.add_all(
                [
                    AiMessage(
                        conversation_id=conversation.id,
                        user_id=user.id,
                        college_id=college.id,
                        role="user",
                        content=f"用户第{turn}轮完整请求和约束",
                    ),
                    AiMessage(
                        conversation_id=conversation.id,
                        user_id=user.id,
                        college_id=college.id,
                        role="assistant",
                        content=f"助手第{turn}轮完整答复",
                    ),
                ]
            )
        current = AiMessage(
            conversation_id=conversation.id,
            user_id=user.id,
            college_id=college.id,
            role="user",
            content="当前最新请求不应混入历史",
            metadata_json={"run_key": "context-current"},
        )
        session.add(current)
        await session.flush()
        context = await load_conversation_context(
            session,
            conversation_id=conversation.id,
            user_id=user.id,
            current_run_key="context-current",
        )
        await session.commit()

        assert len(context.history) == PROTECTED_TURNS * 2
        assert all("第0轮" not in item["content"] for item in context.history)
        assert "第0轮" in context.compressed_summary
        assert "当前最新请求" not in "\n".join(item["content"] for item in context.history)
        assert current.id in context.protected_message_ids

        snapshot = await session.scalar(
            select(AiContextSnapshot).where(
                AiContextSnapshot.conversation_id == conversation.id
            )
        )
        assert snapshot is not None
        version = snapshot.version
        summary = snapshot.summary
        again = await load_conversation_context(
            session,
            conversation_id=conversation.id,
            user_id=user.id,
            current_run_key="context-current",
        )
        assert again.compressed_summary == summary
        assert snapshot.version == version


@pytest.mark.asyncio
async def test_context_is_scoped_to_the_requesting_user(seeded) -> None:
    factory, college, _, user, other_user, *_ = seeded
    async with factory() as session:
        conversation = AiConversation(
            user_id=user.id,
            college_id=college.id,
            title="隔离测试",
            graph_thread_id="context-tenant-scope",
        )
        session.add(conversation)
        await session.flush()
        session.add(
            AiMessage(
                conversation_id=conversation.id,
                user_id=user.id,
                college_id=college.id,
                role="user",
                content="只属于本人",
                created_at=datetime.now() - timedelta(days=1),
            )
        )
        await session.commit()
        result = await load_conversation_context(
            session,
            conversation_id=conversation.id,
            user_id=other_user.id,
            current_run_key="none",
        )
    assert result.history == []
    assert result.compressed_summary == ""


@pytest.mark.asyncio
async def test_expired_raw_message_is_not_retained_through_context_snapshot(seeded) -> None:
    factory, college, _, user, *_ = seeded
    async with factory() as session:
        conversation = AiConversation(
            user_id=user.id,
            college_id=college.id,
            title="摘要过期测试",
            graph_thread_id="context-expiry",
        )
        session.add(conversation)
        await session.flush()
        expired = AiMessage(
            conversation_id=conversation.id,
            user_id=user.id,
            college_id=college.id,
            role="user",
            content="已过期的敏感实验项目事实",
            expires_at=datetime.now() - timedelta(days=1),
        )
        session.add(expired)
        await session.flush()
        snapshot = AiContextSnapshot(
            conversation_id=conversation.id,
            user_id=user.id,
            summary="已过期的敏感实验项目事实",
            source_message_ids=[expired.id],
            through_message_id=expired.id,
        )
        session.add(snapshot)
        await session.commit()

        result = await load_conversation_context(
            session,
            conversation_id=conversation.id,
            user_id=user.id,
            current_run_key="context-expiry-run",
        )

        assert "敏感实验项目事实" not in result.compressed_summary
        assert result.history == []
        assert snapshot.summary == ""
