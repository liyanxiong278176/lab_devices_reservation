from datetime import datetime, timedelta

import pytest
from app.ai.retention import purge_expired_conversations
from app.infrastructure.db.models import AiConfirmation, AiConversation, AiMessage, AiRun
from sqlalchemy import select


@pytest.mark.asyncio
async def test_retention_removes_only_expired_inactive_conversations(seeded) -> None:
    factory, college, _other_college, user, *_ = seeded
    now = datetime(2026, 9, 24, 12, 0, 0)
    old_time = now - timedelta(days=181)
    recent_time = now - timedelta(days=30)

    async with factory() as session:
        expired = AiConversation(
            user_id=user.id,
            college_id=college.id,
            title="已过期的对话",
            graph_thread_id="retention-expired",
            created_at=old_time,
            updated_at=old_time,
        )
        running = AiConversation(
            user_id=user.id,
            college_id=college.id,
            title="正在执行的对话",
            graph_thread_id="retention-running",
            created_at=old_time,
            updated_at=old_time,
        )
        pending = AiConversation(
            user_id=user.id,
            college_id=college.id,
            title="等待确认的对话",
            graph_thread_id="retention-pending",
            created_at=old_time,
            updated_at=old_time,
        )
        recent = AiConversation(
            user_id=user.id,
            college_id=college.id,
            title="最近的对话",
            graph_thread_id="retention-recent",
            created_at=recent_time,
            updated_at=recent_time,
        )
        session.add_all([expired, running, pending, recent])
        await session.flush()
        expired_id, running_id, pending_id, recent_id = (
            expired.id,
            running.id,
            pending.id,
            recent.id,
        )
        session.add_all(
            [
                AiMessage(
                    conversation_id=expired_id,
                    user_id=user.id,
                    college_id=college.id,
                    role="user",
                    content="应按保留周期清理的正文",
                ),
                AiRun(
                    run_key="retention-running-run",
                    conversation_id=running_id,
                    user_id=user.id,
                    college_id=college.id,
                    status="RUNNING",
                    input_text="仍在执行",
                ),
                AiRun(
                    run_key="retention-pending-run",
                    conversation_id=pending_id,
                    user_id=user.id,
                    college_id=college.id,
                    status="WAITING_CONFIRMATION",
                    input_text="等待用户确认",
                ),
            ]
        )
        await session.flush()
        pending_run = await session.scalar(
            select(AiRun).where(AiRun.run_key == "retention-pending-run")
        )
        assert pending_run is not None
        session.add(
            AiConfirmation(
                run_id=pending_run.id,
                conversation_id=pending_id,
                user_id=user.id,
                college_id=college.id,
                tool_name="create_reservation",
                arguments_json={},
                preview_json={},
                status="PENDING",
                expires_at=now + timedelta(minutes=5),
            )
        )
        await session.commit()

    removed = await purge_expired_conversations(factory, 180, now=now, batch_size=10)

    async with factory() as session:
        remaining = set((await session.scalars(select(AiConversation.id))).all())
        remaining_messages = list(
            (
                await session.scalars(
                    select(AiMessage).where(AiMessage.conversation_id == expired_id)
                )
            ).all()
        )
    assert removed == 1
    assert expired_id not in remaining
    assert not remaining_messages
    assert {running_id, pending_id, recent_id}.issubset(remaining)
