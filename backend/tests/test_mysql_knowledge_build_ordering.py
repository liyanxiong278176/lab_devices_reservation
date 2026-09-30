"""MySQL locking integration for the per-document knowledge-build FIFO gate.

Set LAB_TEST_MYSQL_DSN to an isolated, migrated MySQL 8 test database to run.
"""

from __future__ import annotations

import asyncio
import os
from datetime import timedelta
from uuid import uuid4

import pytest
from app.ai.knowledge_build import enqueue_knowledge_build
from app.core.settings import Settings
from app.infrastructure.db.models import (
    College,
    KnowledgeBuildJob,
    KnowledgeDocument,
    OutboxTask,
    User,
)
from app.infrastructure.tasks.worker import OutboxWorker, utcnow_naive
from fastapi import FastAPI
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_mysql_outbox_fifo_allows_other_documents_to_progress() -> None:
    dsn = os.getenv("LAB_TEST_MYSQL_DSN")
    if not dsn:
        pytest.skip("set LAB_TEST_MYSQL_DSN to an isolated migrated MySQL 8 database")

    engine = create_async_engine(dsn, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    app = FastAPI()
    app.state.settings = Settings(
        environment="test",
        mysql_dsn=dsn,
        outbox_worker_concurrency=4,
        outbox_claim_timeout_seconds=300,
        outbox_max_attempts=5,
    )
    app.state.session_factory = factory
    first_worker = OutboxWorker(app)
    second_worker = OutboxWorker(app)
    created_document_ids: list[int] = []
    created_job_ids: list[str] = []
    aggregate_keys: list[str] = []

    try:
        async with factory() as session:
            user_id = await session.scalar(select(User.id).order_by(User.id).limit(1))
            college_id = await session.scalar(select(College.id).order_by(College.id).limit(1))
            if user_id is None:
                pytest.skip("the isolated MySQL test database needs one seeded user")

            documents = [
                KnowledgeDocument(
                    college_id=college_id,
                    title=f"FIFO integration {uuid4()}",
                    source_type="FAQ",
                    body="MySQL Outbox FIFO integration fixture.",
                    version=1,
                    build_sequence=0,
                    status="DRAFT",
                    created_by=user_id,
                    checksum="a" * 64,
                    parse_status="QUEUED",
                )
                for _ in range(2)
            ]
            session.add_all(documents)
            await session.flush()
            created_document_ids = [document.id for document in documents]
            aggregate_keys = [f"ai-knowledge:{document.id}" for document in documents]

            first = enqueue_knowledge_build(
                session, documents[0], requested_by=user_id, build_kind="TEXT"
            )
            second = enqueue_knowledge_build(
                session, documents[0], requested_by=user_id, build_kind="TEXT"
            )
            unrelated = enqueue_knowledge_build(
                session, documents[1], requested_by=user_id, build_kind="TEXT"
            )
            created_job_ids = [first.id, second.id, unrelated.id]
            await session.commit()

        keys = [
            f"ai-knowledge-build:{job_id}:dispatch:0" for job_id in created_job_ids
        ]
        async with factory() as session:
            outbox_rows = list(
                (
                    await session.scalars(
                        select(OutboxTask).where(OutboxTask.task_key.in_(keys))
                    )
                ).all()
            )
            assert len(outbox_rows) == 3
            assert all(row.status == "PENDING" for row in outbox_rows)
            due_time = utcnow_naive() - timedelta(seconds=5)
            for row in outbox_rows:
                row.execute_at = due_time
            await session.commit()
        first_claim, second_claim = await asyncio.gather(
            first_worker._claim_one(only_task_key=keys[0]),
            second_worker._claim_one(only_task_key=keys[1]),
        )
        assert first_claim is not None, "first FIFO task should always be claimable"
        assert second_claim is None, f"a later sequence was claimed concurrently: {second_claim}"

        unrelated_claim = await second_worker._claim_one(only_task_key=keys[2])
        assert unrelated_claim is not None

        async with factory() as session:
            first_job = await session.get(KnowledgeBuildJob, created_job_ids[0])
            second_job = await session.get(KnowledgeBuildJob, created_job_ids[1])
            assert first_job is not None and second_job is not None
            assert first_job.sequence == 1
            assert second_job.sequence == 2
            assert second_job.stage in {"QUEUED", "WAITING_ORDER"}
            first_job.status = "COMPLETED"
            first_job.stage = "COMPLETED"
            first_job.completed_at = utcnow_naive()
            await session.commit()

        await first_worker._mark_completed(first_claim[0])
        second_claim = await second_worker._claim_one(only_task_key=keys[1])
        assert second_claim is not None

    finally:
        async with factory() as session:
            if aggregate_keys:
                await session.execute(
                    delete(OutboxTask).where(OutboxTask.aggregate_key.in_(aggregate_keys))
                )
            if created_job_ids:
                await session.execute(
                    delete(KnowledgeBuildJob).where(KnowledgeBuildJob.id.in_(created_job_ids))
                )
            if created_document_ids:
                await session.execute(
                    delete(KnowledgeDocument).where(
                        KnowledgeDocument.id.in_(created_document_ids)
                    )
                )
            await session.commit()
        await engine.dispose()
