from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

import pymupdf
import pytest
from app.ai import knowledge_build
from app.ai.knowledge_build import (
    PermanentBuildError,
    TransientBuildError,
    enqueue_knowledge_build,
    is_transient_build_error,
    mark_build_failed,
    mark_build_retrying,
    process_knowledge_build_job,
    reconcile_knowledge_build_jobs,
)
from app.auth.csrf import enforce_csrf
from app.auth.security import Principal, get_current_principal
from app.core.metrics import MetricsRegistry
from app.core.settings import Settings
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.db.models import (
    KnowledgeBuildJob,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSection,
    OutboxTask,
)
from app.infrastructure.db.session import get_db
from app.infrastructure.tasks.worker import OutboxWorker, utcnow_naive
from app.main import create_app
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select


class InMemoryIndex:
    def __init__(self, *, fail_on_calls: set[int] | None = None) -> None:
        self.calls = 0
        self.fail_on_calls = set(fail_on_calls or ())
        self.point_ids: list[str] = []

    async def upsert_chunks(self, **kwargs):
        self.calls += 1
        if self.calls in self.fail_on_calls:
            self.fail_on_calls.remove(self.calls)
            raise TransientBuildError("simulated vector write interruption")
        ids = [
            str(
                uuid5(
                    NAMESPACE_URL,
                    f"lab-knowledge:{kwargs['document_id']}:v{kwargs['version']}:{index}",
                )
            )
            for index in kwargs["chunk_indices"]
        ]
        self.point_ids.extend(ids)
        return ids

    async def close(self) -> None:
        return None


def _install_worker_dependencies(monkeypatch, factory, index: InMemoryIndex) -> None:
    class DisposableEngine:
        async def dispose(self) -> None:
            return None

    monkeypatch.setattr(knowledge_build, "build_engine", lambda _settings: DisposableEngine())
    monkeypatch.setattr(knowledge_build, "build_session_factory", lambda _engine: factory)
    monkeypatch.setattr(knowledge_build, "QdrantKnowledgeStore", lambda *_args, **_kwargs: index)

    async def test_embedding_runtime(*_args, **_kwargs):
        return SimpleNamespace(model="test-embedding")

    monkeypatch.setattr(knowledge_build, "_embedding_runtime", test_embedding_runtime)


async def _make_build_document(
    factory,
    college,
    user,
    *,
    body: str = "",
    source_path: Path | None = None,
    build_kind: str = "TEXT",
    status: str = "DRAFT",
    version: int = 1,
    active_version: int | None = None,
    reviewed_text: str | None = None,
):
    async with factory() as session:
        document = KnowledgeDocument(
            college_id=college.id,
            title="异步构建测试文档",
            source_type="SOP",
            body=body,
            version=version,
            active_version=active_version,
            status=status,
            created_by=user.id,
            checksum="a" * 64,
            source_file_path=str(source_path) if source_path else None,
            source_file_name=source_path.name if source_path else None,
            source_sha256="b" * 64 if source_path else None,
            parse_status="UPLOADED" if source_path else "NOT_REQUESTED",
            reviewed_text=reviewed_text,
        )
        session.add(document)
        await session.flush()
        job = enqueue_knowledge_build(
            session,
            document,
            requested_by=user.id,
            build_kind=build_kind,
        )
        await session.commit()
        await session.refresh(document)
        await session.refresh(job)
        return document.id, job.id, job.celery_task_id


def _make_pdf(
    path: Path,
    text: str = "Laboratory equipment reservation and safe operation workflow for testing.",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), text)
        document.save(path)


@pytest.mark.asyncio
async def test_upload_returns_202_persists_file_job_and_filters_status_by_tenant(
    seeded, tmp_path: Path
) -> None:
    factory, college, other_college, manager, other_user, *_ = seeded
    actor = {
        "value": Principal(
            user_id=manager.id,
            username=manager.username,
            college_id=college.id,
            roles=("LAB_ADMIN",),
            token_type="access",
            token_id="knowledge-build-upload-test",
            permissions=("ai:knowledge:manage", "ai:use"),
        )
    }
    settings = Settings(
        environment="test",
        mysql_dsn="sqlite+aiosqlite:///:memory:",
        cors_origins=["http://test"],
        enable_workers=False,
        rate_limit_enabled=False,
        upload_dir=str(tmp_path),
    )
    app = create_app(settings)

    async def override_db():
        async with factory() as session:
            yield session

    async def override_principal() -> Principal:
        return actor["value"]

    async def no_csrf() -> None:
        return None

    async def no_rate_limit() -> None:
        return None

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_principal] = override_principal
    app.dependency_overrides[enforce_csrf] = no_csrf
    app.dependency_overrides[enforce_authenticated_rate_limit] = no_rate_limit
    app.state.session_factory = factory
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v2/ai/knowledge/upload",
                data={"title": "异步上传文档", "source_type": "SOP"},
                files={"file": ("guide.pdf", b"%PDF-1.7\nfixture", "application/pdf")},
            )
            assert response.status_code == 202, response.text
            accepted = response.json()["data"]
            assert accepted["document_id"] > 0
            assert accepted["job_id"]
            assert accepted["task_id"]

            async with factory() as session:
                document = await session.get(KnowledgeDocument, accepted["document_id"])
                job = await session.get(KnowledgeBuildJob, accepted["job_id"])
                outbox = await session.scalar(
                    select(OutboxTask).where(
                        OutboxTask.task_type == "AI_KNOWLEDGE_BUILD_DISPATCH",
                        OutboxTask.payload["job_id"].as_string() == accepted["job_id"],
                    )
                )
                assert document is not None and Path(document.source_file_path or "").is_file()
                assert job is not None and job.college_id == college.id
                assert outbox is not None and set(outbox.payload) == {"job_id", "celery_task_id"}

                job.status = "COMPLETED"
                job.stage = "COMPLETED"
                job.progress_percent = 100
                job.completed_units = 1
                job.total_units = 1
                await session.commit()

            status_response = await client.get(
                f"/api/v2/ai/knowledge/{accepted['document_id']}/build-jobs/{accepted['job_id']}"
            )
            assert status_response.status_code == 200
            assert status_response.json()["data"]["status"] == "COMPLETED"
            assert status_response.json()["data"]["progress_percent"] == 100

            actor["value"] = Principal(
                user_id=other_user.id,
                username=other_user.username,
                college_id=other_college.id,
                roles=("LAB_ADMIN",),
                token_type="access",
                token_id="knowledge-build-cross-tenant",
                permissions=("ai:knowledge:manage", "ai:use"),
            )
            denied = await client.get(
                f"/api/v2/ai/knowledge/{accepted['document_id']}/build-jobs/{accepted['job_id']}"
            )
            assert denied.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_build_outbox_preserves_order_without_blocking_other_documents(seeded) -> None:
    factory, college, _, user, *_ = seeded
    settings = Settings(
        environment="test",
        mysql_dsn="sqlite+aiosqlite:///:memory:",
        enable_workers=False,
        outbox_worker_concurrency=4,
    )
    app = FastAPI()
    app.state.settings = settings
    app.state.session_factory = factory
    worker = OutboxWorker(app)

    document_id, first_job_id, _ = await _make_build_document(
        factory, college, user, body="同一文档第一个构建任务的有效测试内容。"
    )
    other_document_id, _, _ = await _make_build_document(
        factory, college, user, body="另一个文档不应被第一个文档的任务阻塞。"
    )
    async with factory() as session:
        document = await session.get(KnowledgeDocument, document_id)
        assert document is not None
        second_job = enqueue_knowledge_build(
            session,
            document,
            requested_by=user.id,
            build_kind="TEXT",
        )
        second_job_id = second_job.id
        second_outbox_key = f"ai-knowledge-build:{second_job.id}:dispatch:0"
        first_task_key = f"ai-knowledge-build:{first_job_id}:dispatch:0"
        first_outbox = await session.scalar(
            select(OutboxTask).where(OutboxTask.task_key == first_task_key)
        )
        assert first_outbox is not None
        # The earlier job has already been published, while its durable state
        # remains QUEUED until a Celery Worker claims it.
        first_outbox.status = "COMPLETED"
        await session.commit()

    assert await worker._claim_one(only_task_key=second_outbox_key) is None
    async with factory() as session:
        second_job = await session.get(KnowledgeBuildJob, second_job_id)
        second_outbox = await session.scalar(
            select(OutboxTask).where(OutboxTask.task_key == second_outbox_key)
        )
        assert second_job is not None and second_job.status == "QUEUED"
        assert second_job.stage == "WAITING_ORDER"
        assert second_outbox is not None and second_outbox.status == "PENDING"

    other_job_id = await _latest_build_job_id(factory, other_document_id)
    other_outbox_key = f"ai-knowledge-build:{other_job_id}:dispatch:0"
    unrelated = await worker._claim_one(only_task_key=other_outbox_key)
    assert unrelated is not None and unrelated[1] == other_outbox_key

    async with factory() as session:
        first_job = await session.get(KnowledgeBuildJob, first_job_id)
        assert first_job is not None
        first_job.status = "FAILED"
        first_job.stage = "FAILED"
        first_job.completed_at = utcnow_naive()
        await session.commit()

    assert await worker._claim_one(only_task_key=second_outbox_key) is None
    async with factory() as session:
        first_job = await session.get(KnowledgeBuildJob, first_job_id)
        assert first_job is not None
        first_job.status = "SKIPPED"
        first_job.stage = "SKIPPED"
        first_job.completed_at = utcnow_naive()
        await session.commit()

    second_claim = await worker._claim_one(only_task_key=second_outbox_key)
    assert second_claim is not None and second_claim[1] == second_outbox_key


async def _latest_build_job_id(factory, document_id: int) -> str:
    async with factory() as session:
        return str(
            await session.scalar(
                select(KnowledgeBuildJob.id)
                .where(KnowledgeBuildJob.document_id == document_id)
                .order_by(KnowledgeBuildJob.sequence.desc())
                .limit(1)
            )
        )


@pytest.mark.asyncio
async def test_failed_build_retry_keeps_sequence_and_skip_is_audited_and_tenant_scoped(
    seeded, tmp_path: Path
) -> None:
    factory, college, other_college, user, other_user, manager, *_ = seeded
    actor = {
        "value": Principal(
            user_id=manager.id,
            username=manager.username,
            college_id=college.id,
            roles=("LAB_ADMIN",),
            token_type="access",
            token_id="knowledge-build-order-manager",
            permissions=("ai:knowledge:manage", "ai:use"),
        )
    }
    settings = Settings(
        environment="test",
        mysql_dsn="sqlite+aiosqlite:///:memory:",
        cors_origins=["http://test"],
        enable_workers=False,
        rate_limit_enabled=False,
        upload_dir=str(tmp_path),
    )
    app = create_app(settings)

    async def override_db():
        async with factory() as session:
            yield session

    async def override_principal() -> Principal:
        return actor["value"]

    async def no_csrf() -> None:
        return None

    async def no_rate_limit() -> None:
        return None

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_principal] = override_principal
    app.dependency_overrides[enforce_csrf] = no_csrf
    app.dependency_overrides[enforce_authenticated_rate_limit] = no_rate_limit
    app.state.session_factory = factory
    document_id, job_id, original_task_id = await _make_build_document(
        factory,
        college,
        user,
        body="可用于验证失败任务同序重试与显式跳过的知识内容。",
        status="PUBLISHED",
        version=2,
        active_version=1,
    )
    async with factory() as session:
        document = await session.get(KnowledgeDocument, document_id)
        job = await session.get(KnowledgeBuildJob, job_id)
        assert document is not None and job is not None
        document.parse_status = "FAILED"
        job.status = "FAILED"
        job.stage = "FAILED"
        job.error_summary = "模拟解析失败"
        job.completed_at = utcnow_naive()
        await session.commit()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            retry_response = await client.post(f"/api/v2/ai/knowledge/{document_id}/parse")
            assert retry_response.status_code == 202, retry_response.text
            retry_data = retry_response.json()["data"]
            assert retry_data["job_id"] == job_id
            assert retry_data["task_id"] != original_task_id

            async with factory() as session:
                retried = await session.get(KnowledgeBuildJob, job_id)
                document = await session.get(KnowledgeDocument, document_id)
                assert retried is not None and document is not None
                sequence = retried.sequence
                assert retried.status == "QUEUED"
                assert document.parse_status == "QUEUED"
                assert document.active_version == 1
                retried.status = "FAILED"
                retried.stage = "FAILED"
                retried.error_summary = "仍无法解析"
                retried.completed_at = utcnow_naive()
                document.parse_status = "FAILED"
                follower = enqueue_knowledge_build(
                    session,
                    document,
                    requested_by=manager.id,
                    build_kind="TEXT",
                )
                follower_id = follower.id
                await session.commit()

            follower_outbox_key = f"ai-knowledge-build:{follower_id}:dispatch:0"
            assert await OutboxWorker(app)._claim_one(only_task_key=follower_outbox_key) is None

            listed = await client.get("/api/v2/ai/knowledge")
            assert listed.status_code == 200, listed.text
            listed_document = next(
                row for row in listed.json()["data"] if row["id"] == document_id
            )
            assert listed_document["build_job"]["job_id"] == follower_id
            assert listed_document["build_job"]["stage"] == "WAITING_ORDER"
            assert listed_document["build_job"]["blocking_job_id"] == job_id
            assert listed_document["build_job"]["blocking_job_status"] == "FAILED"

            ordered_retry = await client.post(
                f"/api/v2/ai/knowledge/{document_id}/build-jobs/{job_id}/retry"
            )
            assert ordered_retry.status_code == 202, ordered_retry.text
            ordered_retry_data = ordered_retry.json()["data"]
            assert ordered_retry_data["job_id"] == job_id
            assert ordered_retry_data["task_id"] != retry_data["task_id"]

            async with factory() as session:
                retried = await session.get(KnowledgeBuildJob, job_id)
                document = await session.get(KnowledgeDocument, document_id)
                assert retried is not None and document is not None
                assert retried.sequence == sequence
                retried.status = "FAILED"
                retried.stage = "FAILED"
                retried.error_summary = "仍无法解析"
                retried.completed_at = utcnow_naive()
                document.parse_status = "FAILED"
                await session.commit()

            skipped_response = await client.post(
                f"/api/v2/ai/knowledge/{document_id}/build-jobs/{job_id}/skip",
                json={"reason": "已确认该文件损坏，等待替换原件"},
            )
            assert skipped_response.status_code == 200, skipped_response.text
            skipped = skipped_response.json()["data"]
            assert skipped["status"] == "SKIPPED"
            assert skipped["skipped_by"] == manager.id
            assert skipped["skip_reason"] == "已确认该文件损坏，等待替换原件"
            assert skipped["skipped_at"]

            async with factory() as session:
                dispatch = await session.scalar(
                    select(OutboxTask)
                    .where(
                        OutboxTask.task_type == "AI_KNOWLEDGE_BUILD_DISPATCH",
                        OutboxTask.payload["job_id"].as_string() == job_id,
                    )
                    .order_by(OutboxTask.id)
                    .limit(1)
                )
                assert dispatch is not None
                dispatch.status = "PROCESSING"
                dispatch.attempts = settings.outbox_max_attempts
                dispatch_id = dispatch.id
                await session.commit()
            await OutboxWorker(app)._mark_failed(
                dispatch_id,
                "broker unavailable after a stale dispatch attempt",
                RuntimeError("broker unavailable"),
            )

            async with factory() as session:
                document = await session.get(KnowledgeDocument, document_id)
                job = await session.get(KnowledgeBuildJob, job_id)
                assert document is not None and job is not None
                assert document.parse_status == "FAILED"
                assert document.active_version == 1
                assert job.sequence == sequence
                assert job.status == "SKIPPED"

            actor["value"] = Principal(
                user_id=other_user.id,
                username=other_user.username,
                college_id=other_college.id,
                roles=("LAB_ADMIN",),
                token_type="access",
                token_id="knowledge-build-cross-tenant-skip",
                permissions=("ai:knowledge:manage", "ai:use"),
            )
            denied = await client.post(
                f"/api/v2/ai/knowledge/{document_id}/build-jobs/{job_id}/skip",
                json={"reason": "不应允许跨学院跳过"},
            )
            assert denied.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_build_backlog_metrics_include_ready_unacked_and_oldest_wait(
    seeded, monkeypatch
) -> None:
    factory, college, _, user, *_ = seeded
    document_id, _, _ = await _make_build_document(
        factory, college, user, body="积压监控测试文档内容。"
    )
    now = utcnow_naive()
    async with factory() as session:
        job = await session.scalar(
            select(KnowledgeBuildJob).where(KnowledgeBuildJob.document_id == document_id)
        )
        assert job is not None
        job.queued_at = now - timedelta(seconds=95)
        outbox = await session.scalar(
            select(OutboxTask).where(
                OutboxTask.task_type == "AI_KNOWLEDGE_BUILD_DISPATCH",
                OutboxTask.payload["job_id"].as_string() == job.id,
            )
        )
        assert outbox is not None
        outbox.execute_at = now + timedelta(seconds=30)
        await session.commit()

    class FakeBroker:
        async def llen(self, _key: str) -> int:
            return 5

        async def zcard(self, _key: str) -> int:
            return 2

        async def zrange(self, *_args, **_kwargs):
            return [(b"delivery-tag", time.time() - 40)]

        async def aclose(self) -> None:
            return None

    class FakeRedis:
        @classmethod
        def from_url(cls, *_args, **_kwargs):
            return FakeBroker()

    import redis.asyncio

    monkeypatch.setattr(redis.asyncio, "Redis", FakeRedis)
    app = FastAPI()
    app.state.settings = Settings(environment="test", cors_origins=[], enable_workers=False)
    app.state.session_factory = factory
    app.state.metrics = MetricsRegistry()
    await OutboxWorker(app)._sample_knowledge_build_backlog()
    rendered = app.state.metrics.render_prometheus()

    assert 'ai_celery_queue_messages{queue="knowledge-build",state="ready"} 5.0' in rendered
    assert 'ai_celery_queue_messages{queue="knowledge-build",state="unacked"} 2.0' in rendered
    assert 'ai_celery_queue_depth{queue="knowledge-build"} 7.0' in rendered
    assert 'ai_celery_queue_metrics_available 1.0' in rendered
    assert 'ai_knowledge_build_jobs{status="queued"} 1.0' in rendered
    assert 'ai_knowledge_build_order_waiters 0.0' in rendered
    assert 'ai_knowledge_build_outbox_pending 1.0' in rendered
    assert 'ai_knowledge_build_completed_per_minute_5m 0.0' in rendered
    assert 'ai_knowledge_build_failure_ratio_5m 0.0' in rendered
    assert 'ai_knowledge_build_oldest_wait_seconds 95.0' in rendered
    assert 'ai_knowledge_build_outbox_oldest_seconds{status="pending"} 95.0' in rendered


@pytest.mark.asyncio
async def test_worker_extracts_pdf_with_pymupdf_and_duplicate_delivery_is_idempotent(
    seeded, tmp_path: Path, monkeypatch
) -> None:
    factory, college, _, user, *_ = seeded
    settings = Settings(
        environment="test",
        mysql_dsn="sqlite+aiosqlite:///:memory:",
        upload_dir=str(tmp_path),
        ai_knowledge_build_embed_batch_size=2,
    )
    source_path = tmp_path / "ai-knowledge" / "guide.pdf"
    _make_pdf(source_path)
    index = InMemoryIndex()
    _install_worker_dependencies(monkeypatch, factory, index)
    document_id, job_id, task_id = await _make_build_document(
        factory,
        college,
        user,
        source_path=source_path,
        build_kind="UPLOAD",
    )

    await process_knowledge_build_job(settings, job_id, task_id)
    calls_after_first_delivery = index.calls
    await process_knowledge_build_job(settings, job_id, task_id)

    async with factory() as session:
        document = await session.get(KnowledgeDocument, document_id)
        job = await session.get(KnowledgeBuildJob, job_id)
        count = int(
            await session.scalar(
                select(func.count())
                .select_from(KnowledgeChunk)
                .where(
                    KnowledgeChunk.document_id == document_id,
                    KnowledgeChunk.version == 1,
                )
            )
            or 0
        )
    assert document is not None and "Laboratory equipment reservation" in (
        document.extracted_text or ""
    )
    assert document.parse_status == "PARSED"
    assert job is not None and job.status == "COMPLETED" and job.progress_percent == 100
    assert count > 0
    assert index.calls == calls_after_first_delivery
    assert len(set(index.point_ids)) == len(index.point_ids)


@pytest.mark.asyncio
async def test_retry_after_partial_vector_write_replaces_staging_rows_without_duplicates(
    seeded, tmp_path: Path, monkeypatch
) -> None:
    factory, college, _, user, *_ = seeded
    settings = Settings(
        environment="test",
        mysql_dsn="sqlite+aiosqlite:///:memory:",
        upload_dir=str(tmp_path),
        ai_knowledge_build_embed_batch_size=1,
    )
    index = InMemoryIndex(fail_on_calls={2})
    _install_worker_dependencies(monkeypatch, factory, index)
    long_text = "\n\n".join(
        f"## 操作步骤 {index}\n设备预约需要先完成培训，然后按照实验室要求检查设备状态。" * 30
        for index in range(4)
    )
    document_id, job_id, task_id = await _make_build_document(
        factory, college, user, body=long_text, build_kind="TEXT"
    )

    with pytest.raises(TransientBuildError):
        await process_knowledge_build_job(settings, job_id, task_id)
    await mark_build_retrying(settings, job_id, task_id, TransientBuildError("retry"))
    await process_knowledge_build_job(settings, job_id, task_id)

    async with factory() as session:
        document = await session.get(KnowledgeDocument, document_id)
        job = await session.get(KnowledgeBuildJob, job_id)
        chunks = list(
            (
                await session.scalars(
                    select(KnowledgeChunk)
                    .where(
                        KnowledgeChunk.document_id == document_id,
                        KnowledgeChunk.version == 1,
                    )
                    .order_by(KnowledgeChunk.chunk_index)
                )
            ).all()
        )
        sections = list(
            (
                await session.scalars(
                    select(KnowledgeSection).where(
                        KnowledgeSection.document_id == document_id,
                        KnowledgeSection.version == 1,
                    )
                )
            ).all()
        )
    assert document is not None and document.parse_status == "PARSED"
    assert job is not None and job.status == "COMPLETED" and job.attempts == 2
    assert len(chunks) > 2
    assert len({chunk.chunk_index for chunk in chunks}) == len(chunks)
    assert len({chunk.point_id for chunk in chunks}) == len(chunks)
    assert len(sections) > 0
    assert len(set(index.point_ids)) < len(index.point_ids)
    assert len({chunk.point_id for chunk in chunks}) == len(set(chunk.point_id for chunk in chunks))


@pytest.mark.asyncio
async def test_failed_rebuild_keeps_old_published_version_queryable(
    seeded, tmp_path: Path, monkeypatch
) -> None:
    factory, college, _, user, *_ = seeded
    settings = Settings(
        environment="test",
        mysql_dsn="sqlite+aiosqlite:///:memory:",
        upload_dir=str(tmp_path),
        ai_knowledge_build_embed_batch_size=1,
    )
    index = InMemoryIndex(fail_on_calls={1})
    _install_worker_dependencies(monkeypatch, factory, index)
    async with factory() as session:
        document = KnowledgeDocument(
            college_id=college.id,
            title="已发布旧版本",
            source_type="SOP",
            body="旧版内容足以验证失败构建期间仍保持有效。",
            version=2,
            active_version=1,
            status="PUBLISHED",
            created_by=user.id,
            checksum="c" * 64,
            parse_status="QUEUED",
            reviewed_text="\n\n".join(
                f"## 新章节 {section}\n" + ("新版设备操作和预约说明。" * 80) for section in range(3)
            ),
        )
        session.add(document)
        await session.flush()
        old_section = KnowledgeSection(
            document_id=document.id,
            version=1,
            section_index=0,
            heading="旧版章节",
            section_path="旧版章节",
            content="旧版内容仍在使用。",
        )
        session.add(old_section)
        await session.flush()
        session.add(
            KnowledgeChunk(
                document_id=document.id,
                version=1,
                college_id=college.id,
                point_id="old-active-point",
                chunk_index=0,
                content="旧版内容仍在使用。",
                parent_section_id=old_section.id,
            )
        )
        job = enqueue_knowledge_build(
            session,
            document,
            requested_by=user.id,
            build_kind="REVIEWED",
        )
        await session.commit()
        document_id, job_id, task_id = document.id, job.id, job.celery_task_id

    with pytest.raises(TransientBuildError):
        await process_knowledge_build_job(settings, job_id, task_id)
    await mark_build_failed(settings, job_id, task_id, PermanentBuildError("failed"))

    async with factory() as session:
        document = await session.get(KnowledgeDocument, document_id)
        old_chunk = await session.scalar(
            select(KnowledgeChunk).where(KnowledgeChunk.point_id == "old-active-point")
        )
        job = await session.get(KnowledgeBuildJob, job_id)
    assert document is not None and document.active_version == 1
    assert document.status == "PUBLISHED"
    assert document.parse_status == "FAILED"
    assert old_chunk is not None and old_chunk.version == 1
    assert job is not None and job.status == "FAILED"


@pytest.mark.asyncio
async def test_empty_pdf_uses_mineru_fallback_and_corrupt_pdf_fails_visibly(
    seeded, tmp_path: Path, monkeypatch
) -> None:
    factory, college, _, user, *_ = seeded
    settings = Settings(
        environment="test",
        mysql_dsn="sqlite+aiosqlite:///:memory:",
        upload_dir=str(tmp_path),
    )
    source_path = tmp_path / "ai-knowledge" / "scanned.pdf"
    _make_pdf(source_path, "scanned fixture")
    index = InMemoryIndex()
    _install_worker_dependencies(monkeypatch, factory, index)

    async def empty_pymupdf(*_args, **_kwargs):
        return ""

    async def mineru_fallback(*_args, **_kwargs):
        return "MinerU OCR fallback produced readable device instructions."

    monkeypatch.setattr(knowledge_build, "_extract_pdf_with_progress", empty_pymupdf)
    monkeypatch.setattr(knowledge_build, "_extract_with_mineru", mineru_fallback)
    document_id, job_id, task_id = await _make_build_document(
        factory, college, user, source_path=source_path, build_kind="UPLOAD"
    )
    await process_knowledge_build_job(settings, job_id, task_id)
    async with factory() as session:
        chunk = await session.scalar(
            select(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id)
        )
    assert chunk is not None
    assert chunk.metadata_json["parser_version"] == "mineru-fallback-v1"

    bad_path = tmp_path / "ai-knowledge" / "corrupt.pdf"
    bad_path.write_bytes(b"%PDF-1.7\nnot a valid PDF")

    async def mineru_unavailable(*_args, **_kwargs):
        raise PermanentBuildError("MinerU 尚未配置；PyMuPDF 未得到可用文本。")

    monkeypatch.setattr(knowledge_build, "_extract_pdf_with_progress", empty_pymupdf)
    monkeypatch.setattr(knowledge_build, "_extract_with_mineru", mineru_unavailable)
    bad_document_id, bad_job_id, bad_task_id = await _make_build_document(
        factory, college, user, source_path=bad_path, build_kind="UPLOAD"
    )
    with pytest.raises(PermanentBuildError):
        await process_knowledge_build_job(settings, bad_job_id, bad_task_id)
    await mark_build_failed(settings, bad_job_id, bad_task_id, PermanentBuildError("invalid"))
    async with factory() as session:
        bad_document = await session.get(KnowledgeDocument, bad_document_id)
        bad_job = await session.get(KnowledgeBuildJob, bad_job_id)
    assert bad_document is not None and bad_document.parse_status == "FAILED"
    assert bad_job is not None and bad_job.status == "FAILED" and bad_job.error_summary


@pytest.mark.asyncio
async def test_reconciler_recovers_lost_dispatch_and_stale_retry_leases(seeded, tmp_path: Path):
    factory, college, _, user, *_ = seeded
    settings = Settings(
        environment="test",
        mysql_dsn="sqlite+aiosqlite:///:memory:",
        upload_dir=str(tmp_path),
        ai_knowledge_build_dispatch_recovery_seconds=60,
        ai_knowledge_build_lease_seconds=60,
        ai_knowledge_build_max_redeliveries=2,
    )
    old = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=10)
    jobs = [
        await _make_build_document(factory, college, user, body=f"body {index}")
        for index in range(3)
    ]
    async with factory() as session:
        queued = await session.get(KnowledgeBuildJob, jobs[0][1])
        processing = await session.get(KnowledgeBuildJob, jobs[1][1])
        exhausted_retry = await session.get(KnowledgeBuildJob, jobs[2][1])
        assert queued is not None and processing is not None and exhausted_retry is not None
        queued.last_dispatched_at = old
        processing.status = "PROCESSING"
        processing.stage = "EMBEDDING"
        processing.started_at = old
        processing.heartbeat_at = old
        exhausted_retry.status = "RETRYING"
        exhausted_retry.stage = "RETRYING"
        exhausted_retry.heartbeat_at = old
        exhausted_retry.redeliveries = settings.ai_knowledge_build_max_redeliveries
        await session.commit()

    recovered = await reconcile_knowledge_build_jobs(factory, settings)
    assert recovered == 2
    async with factory() as session:
        queued = await session.get(KnowledgeBuildJob, jobs[0][1])
        processing = await session.get(KnowledgeBuildJob, jobs[1][1])
        exhausted_retry = await session.get(KnowledgeBuildJob, jobs[2][1])
        assert queued is not None and processing is not None and exhausted_retry is not None
        assert queued.status == "QUEUED" and queued.dispatch_recoveries == 1
        assert queued.celery_task_id != jobs[0][2]
        assert processing.status == "QUEUED" and processing.redeliveries == 1
        assert processing.celery_task_id != jobs[1][2]
        assert exhausted_retry.status == "FAILED"
        assert exhausted_retry.error_summary
        dispatches = list(
            (
                await session.scalars(
                    select(OutboxTask).where(OutboxTask.task_type == "AI_KNOWLEDGE_BUILD_DISPATCH")
                )
            ).all()
        )
    assert len(dispatches) == 5


@pytest.mark.asyncio
async def test_broker_publish_failure_is_retried_then_exposed_as_failed(
    seeded, tmp_path: Path, monkeypatch
) -> None:
    factory, college, _, user, *_ = seeded
    document_id, job_id, _task_id = await _make_build_document(
        factory, college, user, body="broker recovery fixture with enough text"
    )
    settings = Settings(
        environment="test",
        mysql_dsn="sqlite+aiosqlite:///:memory:",
        upload_dir=str(tmp_path),
        outbox_max_attempts=2,
        outbox_retry_base_seconds=1,
    )
    app = SimpleNamespace(
        state=SimpleNamespace(session_factory=factory, settings=settings, metrics=None)
    )

    from app.infrastructure.tasks import celery_app as celery_module

    def broker_unavailable(*_args, **_kwargs):
        raise ConnectionError("simulated Redis outage")

    monkeypatch.setattr(
        celery_module.build_knowledge_document,
        "apply_async",
        broker_unavailable,
    )
    worker = OutboxWorker(app)
    assert await worker.run_once()
    async with factory() as session:
        outbox = await session.scalar(
            select(OutboxTask).where(OutboxTask.task_type == "AI_KNOWLEDGE_BUILD_DISPATCH")
        )
        job = await session.get(KnowledgeBuildJob, job_id)
        assert outbox is not None and job is not None
        assert outbox.status == "PENDING" and outbox.attempts == 1
        assert job.status == "QUEUED"
        outbox.execute_at = utcnow_naive() - timedelta(seconds=1)
        await session.commit()

    assert await worker.run_once()
    async with factory() as session:
        outbox = await session.scalar(
            select(OutboxTask).where(OutboxTask.task_type == "AI_KNOWLEDGE_BUILD_DISPATCH")
        )
        job = await session.get(KnowledgeBuildJob, job_id)
        document = await session.get(KnowledgeDocument, document_id)
    assert outbox is not None and outbox.status == "FAILED" and outbox.attempts == 2
    assert job is not None and job.status == "FAILED" and job.error_summary
    assert document is not None and document.parse_status == "FAILED"


def test_transient_classification_excludes_qdrant_inference_configuration_errors() -> None:
    class ProviderResponse(Exception):
        def __init__(self, status_code: int, message: str) -> None:
            super().__init__(message)
            self.status_code = status_code

    assert is_transient_build_error(ProviderResponse(429, "rate limited"))
    assert is_transient_build_error(ProviderResponse(503, "provider unavailable"))
    assert not is_transient_build_error(ProviderResponse(400, "invalid payload"))
    assert not is_transient_build_error(
        ProviderResponse(500, "InferenceService is not initialized")
    )


def test_celery_task_marks_failure_after_bounded_transient_retries(monkeypatch) -> None:
    from app.infrastructure.tasks import celery_app as celery_module

    settings = Settings(environment="test")
    calls: list[tuple[str, object]] = []

    async def transient_failure(*_args, **_kwargs):
        raise TransientBuildError("simulated provider throttle")

    async def record_retry(_settings, job_id, task_id, error):
        calls.append(("retrying", (job_id, task_id, type(error).__name__)))

    async def record_failure(_settings, job_id, task_id, error, *, permanent=None):
        calls.append(("failed", (job_id, task_id, type(error).__name__, permanent)))

    monkeypatch.setattr(celery_module, "get_settings", lambda: settings)
    monkeypatch.setattr(knowledge_build, "process_knowledge_build_job", transient_failure)
    monkeypatch.setattr(knowledge_build, "mark_build_retrying", record_retry)
    monkeypatch.setattr(knowledge_build, "mark_build_failed", record_failure)

    result = celery_module.build_knowledge_document.apply(
        args=("job-retry-limit", "task-retry-limit"),
        retries=knowledge_build.MAX_CELERY_RETRIES,
        throw=True,
    )

    assert result.successful()
    assert calls == [
        ("failed", ("job-retry-limit", "task-retry-limit", "TransientBuildError", False))
    ]
