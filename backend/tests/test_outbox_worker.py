from datetime import UTC, datetime, timedelta

import pytest
from app.core.settings import Settings
from app.infrastructure.db.models import Notification, OutboxTask
from app.infrastructure.tasks.worker import OutboxWorker
from fastapi import FastAPI
from sqlalchemy import select


@pytest.mark.asyncio
async def test_outbox_notification_is_processed_and_completed(seeded) -> None:
    factory, _, _, student1, _, _, _, _ = seeded
    app = FastAPI()
    app.state.settings = Settings(environment="test", cors_origins=[], enable_workers=False)
    app.state.session_factory = factory
    worker = OutboxWorker(app, poll_seconds=0.01)
    async with factory() as session:
        session.add(
            OutboxTask(
                task_key="test:notification:001",
                task_type="NOTIFICATION",
                college_id=student1.college_id,
                payload={
                    "user_id": student1.id,
                    "college_id": student1.college_id,
                    "title": "测试通知",
                    "content": "任务可重试且可持久化",
                },
                execute_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        await session.commit()

    assert await worker.run_once() is True

    async with factory() as session:
        task = await session.scalar(
            select(OutboxTask).where(OutboxTask.task_key == "test:notification:001")
        )
        notification = await session.scalar(
            select(Notification).where(Notification.user_id == student1.id)
        )
        assert task is not None and task.status == "COMPLETED"
        assert notification is not None and notification.content == "任务可重试且可持久化"


@pytest.mark.asyncio
async def test_stale_processing_task_is_reclaimed_after_worker_restart(seeded) -> None:
    factory, _, _, student1, _, _, _, _ = seeded
    app = FastAPI()
    app.state.settings = Settings(
        environment="test",
        cors_origins=[],
        enable_workers=False,
        outbox_claim_timeout_seconds=1,
    )
    app.state.session_factory = factory
    worker = OutboxWorker(app, poll_seconds=0.01)
    async with factory() as session:
        session.add(
            OutboxTask(
                task_key="test:notification:stale-001",
                task_type="NOTIFICATION",
                college_id=student1.college_id,
                payload={
                    "user_id": student1.id,
                    "college_id": student1.college_id,
                    "title": "恢复任务",
                    "content": "进程重启后继续处理",
                },
                status="PROCESSING",
                attempts=1,
                claimed_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=5),
                execute_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        await session.commit()

    assert await worker.run_once() is True
    async with factory() as session:
        task = await session.scalar(
            select(OutboxTask).where(OutboxTask.task_key == "test:notification:stale-001")
        )
        notification = await session.scalar(
            select(Notification).where(Notification.title == "恢复任务")
        )
        assert task is not None and task.status == "COMPLETED"
        assert notification is not None
