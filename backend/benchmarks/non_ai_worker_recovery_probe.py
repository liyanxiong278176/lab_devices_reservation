"""Exercise durable outbox lease recovery and duplicate replay in a fresh process.

Use an isolated MySQL schema. Seed the fixture with e2e_fixture.py before this
probe and remove that fixture after verification.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.settings import Settings
from app.infrastructure.db.models import Notification, OutboxTask, User
from app.infrastructure.db.session import build_engine, build_session_factory
from app.infrastructure.notifications.realtime import NotificationHub
from app.infrastructure.tasks.worker import OutboxWorker
from fastapi import FastAPI
from sqlalchemy import func, select


def task_key(prefix: str) -> str:
    return f"acceptance:{prefix}:notification-restart"


async def seed(prefix: str) -> None:
    engine = build_engine(Settings())
    factory = build_session_factory(engine)
    try:
        async with factory() as session:
            user = await session.scalar(select(User).where(User.username == f"{prefix}-user"))
            if user is None:
                raise RuntimeError("seed the isolated e2e fixture before this probe")
            now = datetime.now(UTC).replace(tzinfo=None)
            session.add(
                OutboxTask(
                    task_key=task_key(prefix),
                    task_type="NOTIFICATION",
                    aggregate_key=f"acceptance:{prefix}",
                    college_id=user.college_id,
                    payload={
                        "user_id": user.id,
                        "college_id": user.college_id,
                        "type": "SYSTEM",
                        "title": "Worker restart recovery probe",
                        "content": "Persisted work recovered after a fresh worker process.",
                    },
                    status="PROCESSING",
                    attempts=1,
                    claimed_at=now
                    - timedelta(seconds=Settings().outbox_claim_timeout_seconds + 1),
                    execute_at=now,
                )
            )
            await session.commit()
        print(f"SEEDED stale processing task {task_key(prefix)}")
    finally:
        await engine.dispose()


async def recover(prefix: str) -> None:
    settings = Settings()
    engine = build_engine(settings)
    factory = build_session_factory(engine)
    app = FastAPI()
    app.state.settings = settings
    app.state.session_factory = factory
    app.state.notification_hub = NotificationHub()
    worker = OutboxWorker(app, poll_seconds=0.01)
    try:
        claimed = await worker._claim_one(only_task_key=task_key(prefix))
        if claimed is None:
            raise AssertionError("fresh worker did not reclaim the expired processing lease")
        await worker._process_claimed(claimed)
        # A retry after the notification commit but before task acknowledgement
        # must not create a second notification for the same durable task key.
        await worker._handle("NOTIFICATION", claimed[3], claimed[1])
        print(f"RECOVERED and replayed {claimed[1]} in a new worker process")
    finally:
        await engine.dispose()


async def verify(prefix: str) -> None:
    engine = build_engine(Settings())
    factory = build_session_factory(engine)
    try:
        async with factory() as session:
            task = await session.scalar(
                select(OutboxTask).where(OutboxTask.task_key == task_key(prefix))
            )
            count = await session.scalar(
                select(func.count(Notification.id)).where(
                    Notification.source_task_key == task_key(prefix)
                )
            )
            if task is None or task.status != "COMPLETED":
                raise AssertionError("stale outbox task did not complete")
            if count != 1:
                raise AssertionError(f"expected one idempotent notification, got {count}")
            print(f"PASS task_status={task.status} notification_count={count}")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("seed", "recover", "verify"))
    parser.add_argument("--prefix", required=True)
    args = parser.parse_args()
    operation = {"seed": seed, "recover": recover, "verify": verify}[args.action]
    asyncio.run(operation(args.prefix))


if __name__ == "__main__":
    main()
