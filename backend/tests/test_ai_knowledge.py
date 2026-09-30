from datetime import datetime
from types import SimpleNamespace

import pytest
from app.ai.knowledge import (
    _is_allowed_mineru_upload_url,
    _reload_active_parse_document,
    poll_mineru_parse,
)
from app.core.settings import Settings
from app.infrastructure.db.models import KnowledgeDocument, OutboxTask
from app.infrastructure.tasks.worker import OutboxWorker
from sqlalchemy import select


@pytest.mark.parametrize(
    "url",
    [
        "https://mineru.oss-cn-shanghai.aliyuncs.com/api-upload/signed?token=opaque",
        "https://cdn-mineru.openxlab.org.cn/api-upload/signed?token=opaque",
        "https://openxlab.org.cn/api-upload/signed?token=opaque",
    ],
)
def test_mineru_signed_upload_url_allows_official_https_hosts(url: str) -> None:
    assert _is_allowed_mineru_upload_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://mineru.oss-cn-shanghai.aliyuncs.com/api-upload/signed",
        "https://mineru.oss-cn-shanghai.aliyuncs.com.attacker.example/upload",
        "https://evil-openxlab.org.cn/upload",
        "https://cdn-mineru.openxlab.org.cn.attacker.example/upload",
        "https://user@mineru.oss-cn-shanghai.aliyuncs.com/upload",
        "https://mineru.oss-cn-shanghai.aliyuncs.com:8443/upload",
        "not-a-url",
    ],
)
def test_mineru_signed_upload_url_rejects_untrusted_urls(url: str) -> None:
    assert not _is_allowed_mineru_upload_url(url)


@pytest.mark.asyncio
async def test_parse_poll_does_not_enqueue_more_work_for_deleting_document(
    seeded, monkeypatch
) -> None:
    factory, college, _, user, *_ = seeded
    async with factory() as session:
        document = KnowledgeDocument(
            college_id=college.id,
            title="删除中的文档",
            source_type="SOP",
            body="内容",
            version=1,
            status="DELETING",
            created_by=user.id,
            checksum="d" * 64,
            parse_status="PROCESSING",
            mineru_task_id="batch-deleting",
        )
        session.add(document)
        await session.commit()
        document_id = document.id

    async def unexpected_provider_call(*_args, **_kwargs):
        raise AssertionError("deleted document must not be sent to MinerU")

    monkeypatch.setattr("app.ai.knowledge.get_component_config", unexpected_provider_call)
    app = SimpleNamespace(
        state=SimpleNamespace(session_factory=factory, settings=Settings(environment="test"))
    )
    await poll_mineru_parse(app, document_id, "batch-deleting", attempt=1)

    async with factory() as session:
        document = await session.get(KnowledgeDocument, document_id)
        pending = list(
            (
                await session.scalars(
                    select(OutboxTask).where(
                        OutboxTask.payload["document_id"].as_integer() == document_id
                    )
                )
            ).all()
        )
    assert document is not None and document.parse_status == "PROCESSING"
    assert pending == []


@pytest.mark.asyncio
async def test_parser_worker_failure_does_not_overwrite_deleted_document(seeded) -> None:
    factory, college, _, user, *_ = seeded
    async with factory() as session:
        document = KnowledgeDocument(
            college_id=college.id,
            title="已删除文档",
            source_type="SOP",
            body="",
            version=1,
            status="DELETED",
            created_by=user.id,
            checksum="e" * 64,
            parse_status="DELETED",
        )
        task = OutboxTask(
            task_key="deleted-doc-parser-failure",
            task_type="AI_KNOWLEDGE_POLL",
            aggregate_key="ai-knowledge:deleted",
            college_id=college.id,
            payload={"document_id": -1},
            status="PROCESSING",
            attempts=1,
            execute_at=datetime.now(),
        )
        session.add_all([document, task])
        await session.flush()
        task.payload = {"document_id": document.id}
        document_id, task_id = document.id, task.id
        await session.commit()

    app = SimpleNamespace(
        state=SimpleNamespace(
            session_factory=factory,
            settings=Settings(environment="test", outbox_max_attempts=1),
            metrics=None,
        )
    )
    worker = OutboxWorker(app)
    await worker._mark_failed(task_id, "test failure", RuntimeError("test"))

    async with factory() as session:
        document = await session.get(KnowledgeDocument, document_id)
    assert document is not None and document.parse_status == "DELETED"


@pytest.mark.asyncio
async def test_parse_finalization_rechecks_deletion_after_external_work() -> None:
    document = SimpleNamespace(
        status="DELETED", parse_status="DELETED", mineru_task_id="batch-1"
    )

    class ConcurrentDelete:
        async def refresh(self, target, *, with_for_update):
            assert with_for_update is True
            target.status = "DELETED"
            target.parse_status = "DELETED"

    assert not await _reload_active_parse_document(
        ConcurrentDelete(), document, "batch-1"
    )
