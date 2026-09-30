from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx
import pymupdf
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.ai.config import get_component_config
from app.ai.dlp import redact_text
from app.ai.knowledge import (
    MAX_MARKDOWN_CHARS,
    MAX_RESULT_ZIP_BYTES,
    MINERU_API,
    MINERU_RESULT_HOSTS,
    _extract_markdown,
    _is_allowed_mineru_upload_url,
)
from app.ai.rag.qdrant_store import QdrantKnowledgeStore, split_document_sections
from app.ai.schemas import KnowledgeBuildJobData
from app.ai.usage import add_aux_usage
from app.core.settings import Settings
from app.infrastructure.db.models import (
    AiAuxUsageEvent,
    KnowledgeBuildJob,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSection,
    OutboxTask,
)
from app.infrastructure.db.session import build_engine, build_session_factory

logger = logging.getLogger(__name__)
TERMINAL_JOB_STATUSES = {"COMPLETED", "FAILED", "CANCELLED", "SKIPPED"}
MAX_CELERY_RETRIES = 3
MINERU_POLL_INTERVAL_SECONDS = 5
MINERU_MAX_POLLS = 240  # Keep the existing parser's 20-minute finite polling window.


class PermanentBuildError(Exception):
    """A document or configuration error that retries cannot repair."""


class TransientBuildError(Exception):
    """A temporary provider, broker-adjacent, database, or vector-store error."""


class StaleBuildJob(Exception):
    """The document was deleted, superseded, or claimed by a newer delivery."""


def enqueue_knowledge_build(
    session,
    document: KnowledgeDocument,
    *,
    requested_by: int,
    build_kind: str,
) -> KnowledgeBuildJob:
    if build_kind not in {"UPLOAD", "TEXT", "REVIEWED"}:
        raise ValueError("unknown knowledge build kind")
    job_id = str(uuid4())
    celery_task_id = str(uuid4())
    now = datetime.now(UTC).replace(tzinfo=None)
    document.build_sequence = int(document.build_sequence or 0) + 1
    job = KnowledgeBuildJob(
        id=job_id,
        document_id=document.id,
        college_id=document.college_id,
        requested_by=requested_by,
        version=document.version,
        sequence=document.build_sequence,
        build_kind=build_kind,
        celery_task_id=celery_task_id,
        status="QUEUED",
        stage="QUEUED",
        progress_percent=0,
        completed_units=0,
        attempts=0,
        redeliveries=0,
        dispatch_recoveries=0,
        queued_at=now,
    )
    session.add(job)
    session.add(
        OutboxTask(
            task_key=f"ai-knowledge-build:{job_id}:dispatch:0",
            task_type="AI_KNOWLEDGE_BUILD_DISPATCH",
            aggregate_key=f"ai-knowledge:{document.id}",
            college_id=document.college_id,
            payload={"job_id": job_id, "celery_task_id": celery_task_id},
            status="PENDING",
            execute_at=now,
        )
    )
    document.parse_status = "QUEUED"
    document.parse_error = None
    return job


def retry_failed_knowledge_build(
    session,
    document: KnowledgeDocument,
    job: KnowledgeBuildJob,
) -> KnowledgeBuildJob:
    """Requeue a failed job in place so it keeps its original document sequence."""
    if job.document_id != document.id or job.status != "FAILED":
        raise ValueError("only a failed job for this document can be retried")
    now = datetime.now(UTC).replace(tzinfo=None)
    celery_task_id = str(uuid4())
    job.celery_task_id = celery_task_id
    job.status = "QUEUED"
    job.stage = "QUEUED"
    job.progress_percent = 0
    job.completed_units = 0
    job.total_units = None
    job.unit = None
    job.heartbeat_at = None
    job.last_dispatched_at = None
    job.error_summary = None
    job.completed_at = None
    job.queued_at = now
    job.skipped_by = None
    job.skipped_at = None
    job.skip_reason = None
    session.add(
        OutboxTask(
            task_key=f"ai-knowledge-build:{job.id}:retry:{celery_task_id}",
            task_type="AI_KNOWLEDGE_BUILD_DISPATCH",
            aggregate_key=f"ai-knowledge:{document.id}",
            college_id=document.college_id,
            payload={"job_id": job.id, "celery_task_id": celery_task_id},
            status="PENDING",
            execute_at=now,
        )
    )
    document.parse_status = "QUEUED"
    document.parse_error = None
    return job


def build_job_data(job: KnowledgeBuildJob) -> KnowledgeBuildJobData:
    return KnowledgeBuildJobData(
        job_id=job.id,
        task_id=job.celery_task_id,
        document_id=job.document_id,
        version=job.version,
        status=job.status,
        stage=job.stage,
        progress_percent=job.progress_percent,
        completed_units=job.completed_units,
        total_units=job.total_units,
        unit=job.unit,
        attempts=job.attempts,
        redeliveries=job.redeliveries,
        dispatch_recoveries=job.dispatch_recoveries,
        error_summary=job.error_summary,
        skipped_by=job.skipped_by,
        skipped_at=job.skipped_at,
        skip_reason=job.skip_reason,
        created_at=job.created_at,
        queued_at=job.queued_at,
        started_at=job.started_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
    )


async def latest_build_jobs(
    session,
    document_ids: list[int],
) -> dict[int, KnowledgeBuildJob]:
    if not document_ids:
        return {}
    ranked = (
        select(
            KnowledgeBuildJob.id.label("job_id"),
            KnowledgeBuildJob.document_id.label("document_id"),
            func.row_number()
            .over(
                partition_by=KnowledgeBuildJob.document_id,
                order_by=(KnowledgeBuildJob.sequence.desc(), KnowledgeBuildJob.id.desc()),
            )
            .label("rank"),
        )
        .where(KnowledgeBuildJob.document_id.in_(document_ids))
        .subquery()
    )
    jobs = list(
        (
            await session.scalars(
                select(KnowledgeBuildJob)
                .join(ranked, ranked.c.job_id == KnowledgeBuildJob.id)
                .where(ranked.c.rank == 1)
            )
        ).all()
    )
    return {job.document_id: job for job in jobs}


async def latest_build_job_data(
    session,
    jobs: dict[int, KnowledgeBuildJob],
) -> dict[int, KnowledgeBuildJobData]:
    """Include the earliest unresolved predecessor when it is a failed job."""
    if not jobs:
        return {}
    unresolved_jobs = list(
        (
            await session.scalars(
                select(KnowledgeBuildJob)
                .where(
                    KnowledgeBuildJob.document_id.in_(jobs),
                    KnowledgeBuildJob.status.in_(
                        ["QUEUED", "PROCESSING", "RETRYING", "FAILED"]
                    ),
                )
                .order_by(KnowledgeBuildJob.document_id, KnowledgeBuildJob.sequence)
            )
        ).all()
    )
    unresolved_by_document: dict[int, list[KnowledgeBuildJob]] = {}
    for predecessor in unresolved_jobs:
        unresolved_by_document.setdefault(predecessor.document_id, []).append(predecessor)

    result: dict[int, KnowledgeBuildJobData] = {}
    for document_id, job in jobs.items():
        data = build_job_data(job)
        predecessor = next(
            (
                candidate
                for candidate in unresolved_by_document.get(document_id, ())
                if candidate.sequence < job.sequence
            ),
            None,
        )
        if predecessor is not None and predecessor.status == "FAILED":
            data.blocking_job_id = predecessor.id
            data.blocking_job_version = predecessor.version
            data.blocking_job_status = predecessor.status
            data.blocking_job_error_summary = predecessor.error_summary
        result[document_id] = data
    return result


async def set_job_dispatched(
    session_factory: async_sessionmaker,
    *,
    job_id: str,
    celery_task_id: str,
) -> None:
    async with session_factory() as session:
        job = await session.scalar(
            select(KnowledgeBuildJob).where(KnowledgeBuildJob.id == job_id).with_for_update()
        )
        if job is None or job.celery_task_id != celery_task_id:
            return
        job.last_dispatched_at = _now()
        if job.stage == "WAITING_ORDER":
            job.stage = "QUEUED"
        await session.commit()


async def reconcile_knowledge_build_jobs(
    session_factory: async_sessionmaker,
    settings: Settings,
    *,
    batch_size: int = 20,
) -> int:
    """Repair lost Redis publications and stale worker leases through the SQL outbox."""
    now = _now()
    dispatch_before = now - timedelta(seconds=settings.ai_knowledge_build_dispatch_recovery_seconds)
    heartbeat_before = now - timedelta(seconds=settings.ai_knowledge_build_lease_seconds)
    recovered = 0
    async with session_factory() as session:
        statement = (
            select(KnowledgeBuildJob)
            .where(
                or_(
                    (KnowledgeBuildJob.status == "QUEUED")
                    & KnowledgeBuildJob.last_dispatched_at.is_not(None)
                    & (KnowledgeBuildJob.last_dispatched_at <= dispatch_before),
                    KnowledgeBuildJob.status.in_(["PROCESSING", "RETRYING"])
                    & KnowledgeBuildJob.heartbeat_at.is_not(None)
                    & (KnowledgeBuildJob.heartbeat_at <= heartbeat_before),
                )
            )
            .order_by(KnowledgeBuildJob.updated_at, KnowledgeBuildJob.id)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        jobs = list((await session.scalars(statement)).all())
        for job in jobs:
            is_stale_worker = job.status in {"PROCESSING", "RETRYING"}
            if is_stale_worker and job.redeliveries >= settings.ai_knowledge_build_max_redeliveries:
                job.status = "FAILED"
                job.stage = "FAILED"
                job.error_summary = "后台 Worker 多次中断，请重新提交文档构建。"
                job.completed_at = now
                document = await session.get(KnowledgeDocument, job.document_id)
                if document is not None and document.status not in {"DELETING", "DELETED"}:
                    document.parse_status = "FAILED"
                    document.parse_error = job.error_summary
                logger.error(
                    "knowledge build abandoned document_id=%s job_id=%s tenant_id=%s "
                    "stage=%s retries=%s reason=worker_lease_exhausted",
                    job.document_id,
                    job.id,
                    job.college_id,
                    job.stage,
                    job.redeliveries,
                )
                continue
            if is_stale_worker:
                job.redeliveries += 1
            job.dispatch_recoveries += 1
            job.celery_task_id = str(uuid4())  # Fence an old process that resumes late.
            job.status = "QUEUED"
            job.stage = "QUEUED"
            job.progress_percent = 0
            job.completed_units = 0
            job.total_units = None
            job.unit = None
            job.heartbeat_at = None
            job.last_dispatched_at = None
            job.error_summary = None
            job.queued_at = now
            session.add(
                OutboxTask(
                    task_key=f"ai-knowledge-build:{job.id}:dispatch:{job.dispatch_recoveries}",
                    task_type="AI_KNOWLEDGE_BUILD_DISPATCH",
                    aggregate_key=f"ai-knowledge:{job.document_id}",
                    college_id=job.college_id,
                    payload={
                        "job_id": job.id,
                        "celery_task_id": job.celery_task_id,
                    },
                    status="PENDING",
                    execute_at=now,
                )
            )
            recovered += 1
        await session.commit()
    return recovered


async def mark_build_retrying(
    settings: Settings,
    job_id: str,
    celery_task_id: str,
    error: BaseException,
) -> None:
    engine = build_engine(settings)
    factory = build_session_factory(engine)
    try:
        async with factory() as session:
            job = await session.scalar(
                select(KnowledgeBuildJob).where(KnowledgeBuildJob.id == job_id).with_for_update()
            )
            if (
                job is None
                or job.celery_task_id != celery_task_id
                or job.status in TERMINAL_JOB_STATUSES
            ):
                return
            job.status = "RETRYING"
            job.stage = "RETRYING"
            job.error_summary = _safe_failure_summary(error, permanent=False)
            job.heartbeat_at = _now()
            await session.commit()
            elapsed_ms = (
                int((job.heartbeat_at - job.started_at).total_seconds() * 1000)
                if job.started_at is not None
                else 0
            )
            logger.warning(
                "knowledge build retrying document_id=%s job_id=%s tenant_id=%s "
                "stage=RETRYING duration_ms=%s attempts=%s error_type=%s",
                job.document_id,
                job.id,
                job.college_id,
                elapsed_ms,
                job.attempts,
                type(error).__name__,
            )
    finally:
        await engine.dispose()


async def mark_build_cancelled(
    settings: Settings,
    job_id: str,
    celery_task_id: str,
) -> None:
    engine = build_engine(settings)
    factory = build_session_factory(engine)
    try:
        async with factory() as session:
            job = await session.scalar(
                select(KnowledgeBuildJob).where(KnowledgeBuildJob.id == job_id).with_for_update()
            )
            if (
                job is None
                or job.celery_task_id != celery_task_id
                or job.status in TERMINAL_JOB_STATUSES
            ):
                return
            document = await session.get(KnowledgeDocument, job.document_id)
            if (
                document is not None
                and document.status not in {"DELETING", "DELETED"}
                and document.version == job.version
            ):
                return
            job.status = "CANCELLED"
            job.stage = "CANCELLED"
            job.completed_at = _now()
            await session.commit()
    finally:
        await engine.dispose()


async def mark_build_failed(
    settings: Settings,
    job_id: str,
    celery_task_id: str,
    error: BaseException,
    *,
    permanent: bool | None = None,
) -> None:
    engine = build_engine(settings)
    factory = build_session_factory(engine)
    try:
        async with factory() as session:
            job = await session.scalar(
                select(KnowledgeBuildJob).where(KnowledgeBuildJob.id == job_id).with_for_update()
            )
            if (
                job is None
                or job.celery_task_id != celery_task_id
                or job.status in TERMINAL_JOB_STATUSES
            ):
                return
            failed_stage = job.stage
            document = await session.scalar(
                select(KnowledgeDocument)
                .where(KnowledgeDocument.id == job.document_id)
                .with_for_update()
            )
            job.status = "FAILED"
            job.stage = "FAILED"
            job.error_summary = _safe_failure_summary(
                error,
                permanent=(
                    isinstance(error, PermanentBuildError) if permanent is None else permanent
                ),
            )
            job.completed_at = _now()
            job.heartbeat_at = job.completed_at
            if document is not None and document.status not in {"DELETING", "DELETED"}:
                document.parse_status = "FAILED"
                document.parse_error = job.error_summary
            await session.commit()
            elapsed_ms = (
                int((job.completed_at - job.started_at).total_seconds() * 1000)
                if job.started_at is not None
                else 0
            )
            logger.error(
                "knowledge build failed document_id=%s job_id=%s tenant_id=%s stage=%s "
                "duration_ms=%s attempts=%s reason=%s error_type=%s",
                job.document_id,
                job.id,
                job.college_id,
                failed_stage,
                elapsed_ms,
                job.attempts,
                job.error_summary,
                type(error).__name__,
            )
    finally:
        await engine.dispose()


async def process_knowledge_build_job(
    settings: Settings,
    job_id: str,
    celery_task_id: str,
) -> None:
    started = time.perf_counter()
    engine = build_engine(settings)
    factory = build_session_factory(engine)
    store: QdrantKnowledgeStore | None = None
    try:
        claimed = await _claim_job(factory, job_id, celery_task_id, settings)
        if claimed is None:
            return
        document_id, document_version, build_kind, tenant_id, attempt_number = claimed
        logger.info(
            "knowledge build started document_id=%s job_id=%s tenant_id=%s stage=%s attempts=%s",
            document_id,
            job_id,
            tenant_id,
            "PARSING" if build_kind == "UPLOAD" else "CHUNKING",
            attempt_number,
        )
        progress = _progress_callback(factory, job_id, celery_task_id)

        async with factory() as session:
            document = await session.get(KnowledgeDocument, document_id)
            if document is None:
                raise PermanentBuildError("知识文档不存在。")
            source_path = document.source_file_path
            source_name = document.source_file_name or "document"
            source_title = document.title
            source_type = document.source_type
            college_id = document.college_id
            lab_id = document.lab_id
            device_id = document.device_id
            allowed_roles = list(document.allowed_roles or ())
            if build_kind == "REVIEWED":
                input_text = document.reviewed_text or ""
            elif build_kind == "TEXT":
                input_text = document.body or ""
            else:
                input_text = ""
        parser_version = "plain-text-v1"

        if build_kind == "UPLOAD":
            if not source_path:
                raise PermanentBuildError("文档原始文件路径缺失，请重新上传。")
            upload_root = (Path(settings.upload_dir).resolve() / "ai-knowledge").resolve()
            path = Path(source_path).resolve()
            if not path.is_relative_to(upload_root) or not path.is_file():
                raise PermanentBuildError("原始文件不存在或路径无效，请重新上传。")
            if path.suffix.lower() == ".pdf":
                await progress(
                    stage="PARSING",
                    progress_percent=None,
                    completed_units=0,
                    total_units=None,
                    unit=None,
                )
                try:
                    input_text = await _extract_pdf_with_progress(
                        path,
                        lambda completed, total: progress(
                            stage="PARSING",
                            progress_percent=int(completed * 100 / total) if total else None,
                            completed_units=completed,
                            total_units=total,
                            unit="pages",
                        ),
                    )
                    parser_version = "pymupdf-sorted-v1"
                except Exception as exc:
                    logger.info(
                        "PyMuPDF extraction failed; document_id=%s job_id=%s error_type=%s",
                        document_id,
                        job_id,
                        type(exc).__name__,
                    )
                    input_text = ""
                if not input_text.strip() or "\ufffd" in input_text:
                    logger.info(
                        "PyMuPDF fallback to MinerU; document_id=%s job_id=%s reason=%s",
                        document_id,
                        job_id,
                        "empty_text_or_replacement_character",
                    )
                    input_text = await _extract_with_mineru(
                        settings,
                        factory,
                        document_id=document_id,
                        version=document_version,
                        job_id=job_id,
                        attempt_number=attempt_number,
                        path=path,
                        file_name=source_name,
                        progress=progress,
                    )
                    parser_version = "mineru-fallback-v1"
            else:
                input_text = await _extract_with_mineru(
                    settings,
                    factory,
                    document_id=document_id,
                    version=document_version,
                    job_id=job_id,
                    attempt_number=attempt_number,
                    path=path,
                    file_name=source_name,
                    progress=progress,
                )
                parser_version = "mineru-v1"

            if not input_text.strip():
                raise PermanentBuildError("解析结果没有可索引的正文内容。")
            redaction = redact_text(input_text[:MAX_MARKDOWN_CHARS])
            input_text = redaction.text
            async with factory() as session:
                current = await _lock_current_document(session, document_id, document_version)
                if current is None:
                    raise StaleBuildJob("document was deleted or superseded")
                current.extracted_text = input_text
                current.dlp_categories = sorted(
                    set(current.dlp_categories or ()) | set(redaction.categories)
                )
                current.parse_error = None
                await session.commit()

        if not input_text.strip():
            raise PermanentBuildError("文档没有可索引的正文内容。")
        redaction = redact_text(input_text[:MAX_MARKDOWN_CHARS])
        input_text = redaction.text
        content_sha256 = hashlib.sha256(input_text.encode("utf-8")).hexdigest()
        section_plans, chunk_plans = split_document_sections(input_text)
        if not chunk_plans:
            raise PermanentBuildError("文档没有可索引的正文内容。")
        if len(chunk_plans) > 100_000:
            raise PermanentBuildError("文档分块数量超出安全上限。")

        embedding_runtime = await _embedding_runtime(factory, settings)
        store = QdrantKnowledgeStore(settings, embedding_runtime)
        section_ids = await _prepare_versioned_sections(
            factory,
            job_id,
            celery_task_id,
            document_id,
            document_version,
            section_plans,
        )
        total_chunks = len(chunk_plans)
        await progress(
            stage="CHUNKING",
            progress_percent=None,
            completed_units=0,
            total_units=None,
            unit=None,
            content_sha256=content_sha256,
        )
        await progress(
            stage="EMBEDDING",
            progress_percent=0,
            completed_units=0,
            total_units=total_chunks,
            unit="chunks",
            content_sha256=content_sha256,
        )
        batch_size = settings.ai_knowledge_build_embed_batch_size
        completed = 0
        for start in range(0, total_chunks, batch_size):
            batch = chunk_plans[start : start + batch_size]
            await _ensure_job_current(
                factory, job_id, celery_task_id, document_id, document_version
            )
            batch_sections = [section_ids[chunk.section_index] for chunk in batch]
            contents = [chunk.content for chunk in batch]
            point_ids = await store.upsert_chunks(
                document_id=document_id,
                title=source_title,
                source_type=source_type,
                college_id=college_id,
                chunks=contents,
                version=document_version,
                chunk_indices=[chunk.index for chunk in batch],
                section_paths=[chunk.section_path for chunk in batch],
                parent_section_ids=batch_sections,
                allowed_roles=[allowed_roles for _ in batch],
                lab_ids=[lab_id for _ in batch],
                device_ids=[device_id for _ in batch],
                index_metadata={
                    "source_sha256": content_sha256,
                    "parser_version": parser_version,
                    "chunker_version": "heading-recursive-v1",
                },
            )
            await _persist_chunk_batch(
                factory,
                job_id,
                celery_task_id,
                document_id,
                document_version,
                batch,
                point_ids,
                section_ids,
                source_title,
                source_type,
                college_id,
                allowed_roles,
                lab_id,
                device_id,
                content_sha256,
                parser_version,
            )
            completed += len(batch)
            await progress(
                stage="EMBEDDING",
                progress_percent=int(completed * 100 / total_chunks),
                completed_units=completed,
                total_units=total_chunks,
                unit="chunks",
                content_sha256=content_sha256,
            )

        await progress(
            stage="INDEXING",
            progress_percent=None,
            completed_units=0,
            total_units=None,
            unit=None,
            content_sha256=content_sha256,
        )
        await _complete_job(
            factory,
            job_id,
            celery_task_id,
            document_id,
            document_version,
            build_kind,
            content_sha256,
            redaction.categories,
            embedding_model=(
                embedding_runtime.model if embedding_runtime is not None else "deterministic-test"
            ),
            total_chunks=total_chunks,
            input_units=sum(len(chunk.content) for chunk in chunk_plans),
        )
        logger.info(
            "knowledge build completed document_id=%s job_id=%s tenant_id=%s stage=COMPLETED "
            "duration_ms=%s retries=%s chunks=%s",
            document_id,
            job_id,
            tenant_id,
            int((time.perf_counter() - started) * 1000),
            await _job_attempts(factory, job_id),
            total_chunks,
        )
    except StaleBuildJob:
        logger.info("knowledge build superseded or deleted job_id=%s", job_id)
        raise
    except Exception:
        raise
    finally:
        if store is not None:
            await store.close()
        await engine.dispose()


async def _claim_job(
    factory: async_sessionmaker,
    job_id: str,
    celery_task_id: str,
    settings: Settings,
) -> tuple[int, int, str, int | None, int] | None:
    async with factory() as session:
        job = await session.scalar(
            select(KnowledgeBuildJob).where(KnowledgeBuildJob.id == job_id).with_for_update()
        )
        if (
            job is None
            or job.celery_task_id != celery_task_id
            or job.status in TERMINAL_JOB_STATUSES
        ):
            return None
        now = _now()
        if (
            job.status == "PROCESSING"
            and job.heartbeat_at is not None
            and (now - job.heartbeat_at).total_seconds() < settings.ai_knowledge_build_lease_seconds
        ):
            return None
        document = await session.scalar(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.id == job.document_id)
            .with_for_update()
        )
        if document is None or document.status in {"DELETING", "DELETED"}:
            job.status = "CANCELLED"
            job.stage = "CANCELLED"
            job.completed_at = now
            await session.commit()
            return None
        if document.version != job.version:
            job.status = "CANCELLED"
            job.stage = "CANCELLED"
            job.completed_at = now
            await session.commit()
            return None
        predecessor = await session.scalar(
            select(KnowledgeBuildJob.id)
            .where(
                KnowledgeBuildJob.document_id == job.document_id,
                KnowledgeBuildJob.sequence < job.sequence,
                KnowledgeBuildJob.status.in_(["QUEUED", "PROCESSING", "RETRYING", "FAILED"]),
            )
            .order_by(KnowledgeBuildJob.sequence)
            .limit(1)
        )
        if predecessor is not None:
            job.status = "QUEUED"
            job.stage = "WAITING_ORDER"
            job.last_dispatched_at = None
            task_key = f"ai-knowledge-build:{job.id}:ordered:{celery_task_id}"
            already_waiting = await session.scalar(
                select(OutboxTask.id).where(OutboxTask.task_key == task_key).limit(1)
            )
            if already_waiting is None:
                session.add(
                    OutboxTask(
                        task_key=task_key,
                        task_type="AI_KNOWLEDGE_BUILD_DISPATCH",
                        aggregate_key=f"ai-knowledge:{job.document_id}",
                        college_id=job.college_id,
                        payload={"job_id": job.id, "celery_task_id": celery_task_id},
                        status="PENDING",
                        execute_at=now,
                    )
                )
            await session.commit()
            logger.info(
                "knowledge build deferred document_id=%s job_id=%s tenant_id=%s "
                "stage=WAITING_ORDER predecessor_job_id=%s",
                document.id,
                job.id,
                job.college_id,
                predecessor,
            )
            return None
        job.status = "PROCESSING"
        job.stage = "PARSING" if job.build_kind == "UPLOAD" else "CHUNKING"
        job.progress_percent = None
        job.completed_units = 0
        job.total_units = None
        job.unit = None
        job.attempts += 1
        job.started_at = job.started_at or now
        job.heartbeat_at = now
        job.error_summary = None
        document.parse_status = "PROCESSING"
        document.parse_error = None
        await session.commit()
        return document.id, document.version, job.build_kind, job.college_id, job.attempts


def _progress_callback(factory, job_id: str, celery_task_id: str):
    async def update_progress(
        *,
        stage: str,
        progress_percent: int | None,
        completed_units: int,
        total_units: int | None,
        unit: str | None,
        content_sha256: str | None = None,
    ) -> bool:
        async with factory() as session:
            job = await session.scalar(
                select(KnowledgeBuildJob).where(KnowledgeBuildJob.id == job_id).with_for_update()
            )
            if (
                job is None
                or job.celery_task_id != celery_task_id
                or job.status in TERMINAL_JOB_STATUSES
            ):
                return False
            document = await session.scalar(
                select(KnowledgeDocument)
                .where(KnowledgeDocument.id == job.document_id)
                .with_for_update()
            )
            if (
                document is None
                or document.status in {"DELETING", "DELETED"}
                or document.version != job.version
            ):
                job.status = "CANCELLED"
                job.stage = "CANCELLED"
                job.completed_at = _now()
                await session.commit()
                return False
            job.status = "PROCESSING"
            job.stage = stage
            job.progress_percent = progress_percent
            job.completed_units = completed_units
            job.total_units = total_units
            job.unit = unit
            job.heartbeat_at = _now()
            if content_sha256 is not None:
                job.content_sha256 = content_sha256
            document.parse_status = "PROCESSING"
            await session.commit()
            return True

    return update_progress


async def _extract_pdf_with_progress(
    path: Path,
    callback: Callable[[int, int], Any],
) -> str:
    loop = asyncio.get_running_loop()

    def report(completed: int, total: int) -> None:
        future = asyncio.run_coroutine_threadsafe(callback(completed, total), loop)
        future.result(timeout=90)

    return await asyncio.to_thread(_extract_pdf_text, path, report)


def _extract_pdf_text(path: Path, report: Callable[[int, int], None]) -> str:
    with pymupdf.open(path) as document:
        total_pages = document.page_count
        pages: list[str] = []
        for index, page in enumerate(document, start=1):
            pages.append(page.get_text("text", sort=True))
            report(index, total_pages)
        return "\n\n".join(page for page in pages if page.strip())


async def _extract_with_mineru(
    settings: Settings,
    factory: async_sessionmaker,
    *,
    document_id: int,
    version: int,
    job_id: str,
    attempt_number: int,
    path: Path,
    file_name: str,
    progress,
) -> str:
    async with factory() as session:
        runtime = await get_component_config(session, settings, "mineru")
    if runtime is None or not runtime.enabled or not runtime.api_key:
        raise PermanentBuildError("MinerU 尚未配置；PyMuPDF 未得到可用文本。")
    headers = {"Authorization": f"Bearer {runtime.api_key}"}
    timeout = httpx.Timeout(90.0, connect=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            response = await client.post(
                f"{MINERU_API}/api/v4/file-urls/batch",
                headers=headers,
                json={
                    "files": [
                        {"name": file_name, "data_id": f"knowledge-{document_id}-v{version}"}
                    ],
                    "model_version": runtime.model,
                    "enable_table": True,
                    "is_ocr": True,
                    "language": "ch",
                },
            )
            response.raise_for_status()
            result = response.json()
            data = result.get("data") or {}
            batch_id = data.get("batch_id")
            upload_urls = data.get("file_urls") or []
            if result.get("code") != 0 or not batch_id or not upload_urls:
                raise PermanentBuildError("MinerU 拒绝了该文档的解析请求。")
            if not _is_allowed_mineru_upload_url(str(upload_urls[0])):
                raise PermanentBuildError("MinerU 返回的上传地址无效。")
            upload = await client.put(str(upload_urls[0]), content=path.read_bytes())
            upload.raise_for_status()
            await progress(
                stage="PARSING",
                progress_percent=None,
                completed_units=0,
                total_units=None,
                unit=None,
            )
            for attempt in range(MINERU_MAX_POLLS):
                await asyncio.sleep(MINERU_POLL_INTERVAL_SECONDS)
                if not await progress(
                    stage="PARSING",
                    progress_percent=None,
                    completed_units=0,
                    total_units=None,
                    unit=None,
                ):
                    raise StaleBuildJob("document was deleted or superseded")
                status_response = await client.get(
                    f"{MINERU_API}/api/v4/extract-results/batch/{batch_id}",
                    headers=headers,
                )
                status_response.raise_for_status()
                status_data = status_response.json()
                if status_data.get("code") != 0:
                    raise TransientBuildError("MinerU 状态查询暂时失败。")
                rows = (status_data.get("data") or {}).get("extract_result") or []
                item = next(
                    (
                        row
                        for row in rows
                        if row.get("data_id") == f"knowledge-{document_id}-v{version}"
                    ),
                    rows[0] if len(rows) == 1 else None,
                )
                if item is None:
                    raise PermanentBuildError("MinerU 返回结果与当前文档不匹配。")
                state = str(item.get("state", ""))
                if state in {"waiting-file", "pending", "running", "converting"}:
                    continue
                if state == "failed":
                    raise PermanentBuildError("MinerU 无法解析该文件，请检查文件内容。")
                if state != "done":
                    raise PermanentBuildError("MinerU 返回了无法识别的解析状态。")
                result_url = urlparse(str(item.get("full_zip_url", "")))
                if result_url.scheme != "https" or result_url.hostname not in MINERU_RESULT_HOSTS:
                    raise PermanentBuildError("MinerU 返回的解析结果地址无效。")
                zip_response = await client.get(str(item["full_zip_url"]))
                zip_response.raise_for_status()
                if len(zip_response.content) > MAX_RESULT_ZIP_BYTES:
                    raise PermanentBuildError("MinerU 解析结果超过大小限制。")
                text = _extract_markdown(zip_response.content)[:MAX_MARKDOWN_CHARS]
                if not text.strip():
                    raise PermanentBuildError("MinerU 没有提取到可用文本。")
                async with factory() as session:
                    event_key = f"knowledge-build:{job_id}:mineru:{attempt_number}"
                    recorded = await session.scalar(
                        select(AiAuxUsageEvent.id).where(AiAuxUsageEvent.event_key == event_key)
                    )
                    if recorded is None:
                        document = await session.get(KnowledgeDocument, document_id)
                        if document is not None:
                            add_aux_usage(
                                session,
                                event_key=event_key,
                                component="mineru",
                                operation="document_parse",
                                model=runtime.model,
                                user_id=document.created_by,
                                college_id=document.college_id,
                                item_count=int(item.get("page_count") or item.get("page_num") or 0),
                                input_units=path.stat().st_size,
                            )
                        await session.commit()
                return text
            raise TransientBuildError("MinerU 文档解析超过 20 分钟处理上限。")
    except (PermanentBuildError, TransientBuildError, StaleBuildJob):
        raise
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in {408, 425, 429} or status >= 500:
            raise TransientBuildError("MinerU 服务暂时不可用。") from exc
        raise PermanentBuildError("MinerU 拒绝了该文档的解析请求。") from exc
    except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
        raise TransientBuildError("MinerU 网络请求超时或连接中断。") from exc


async def _embedding_runtime(factory, settings: Settings):
    async with factory() as session:
        runtime = await get_component_config(session, settings, "embedding")
    if settings.environment != "test" and (
        runtime is None or not runtime.enabled or not runtime.api_key
    ):
        raise PermanentBuildError("Embedding 服务尚未配置或未启用。")
    return runtime


async def _prepare_versioned_sections(
    factory,
    job_id: str,
    celery_task_id: str,
    document_id: int,
    version: int,
    plans,
) -> dict[int, int]:
    async with factory() as session:
        await _require_current_job(session, job_id, celery_task_id, document_id, version)
        await session.execute(
            delete(KnowledgeChunk).where(
                KnowledgeChunk.document_id == document_id,
                KnowledgeChunk.version == version,
            )
        )
        await session.execute(
            delete(KnowledgeSection).where(
                KnowledgeSection.document_id == document_id,
                KnowledgeSection.version == version,
            )
        )
        rows = {
            plan.index: KnowledgeSection(
                document_id=document_id,
                version=version,
                section_index=plan.index,
                heading=plan.heading,
                section_path=plan.section_path,
                content=plan.content,
            )
            for plan in plans
        }
        session.add_all(rows.values())
        await session.flush()
        for plan in plans:
            if plan.parent_index is not None:
                rows[plan.index].parent_section_id = rows[plan.parent_index].id
        await session.flush()
        section_ids = {index: int(row.id) for index, row in rows.items()}
        await session.commit()
        return section_ids


async def _persist_chunk_batch(
    factory,
    job_id: str,
    celery_task_id: str,
    document_id: int,
    version: int,
    chunks,
    point_ids: list[str],
    section_ids: dict[int, int],
    title: str,
    source_type: str,
    college_id: int | None,
    allowed_roles: list[str],
    lab_id: int | None,
    device_id: int | None,
    content_sha256: str,
    parser_version: str,
) -> None:
    if len(chunks) != len(point_ids):
        raise PermanentBuildError("向量服务返回的索引数量与分块数量不匹配。")
    async with factory() as session:
        await _require_current_job(session, job_id, celery_task_id, document_id, version)
        indices = [chunk.index for chunk in chunks]
        await session.execute(
            delete(KnowledgeChunk).where(
                KnowledgeChunk.document_id == document_id,
                KnowledgeChunk.version == version,
                KnowledgeChunk.chunk_index.in_(indices),
            )
        )
        rows = []
        for chunk, point_id in zip(chunks, point_ids, strict=True):
            parent_id = section_ids[chunk.section_index]
            rows.append(
                KnowledgeChunk(
                    document_id=document_id,
                    version=version,
                    college_id=college_id,
                    point_id=point_id,
                    chunk_index=chunk.index,
                    content=chunk.content,
                    parent_section_id=parent_id,
                    metadata_json={
                        "title": title,
                        "source_type": source_type,
                        "version": version,
                        "section_path": chunk.section_path,
                        "parent_section_id": parent_id,
                        "allowed_roles": allowed_roles,
                        "lab_id": lab_id,
                        "device_id": device_id,
                        "source_sha256": content_sha256,
                        "parser_version": parser_version,
                        "chunker_version": "heading-recursive-v1",
                    },
                )
            )
        session.add_all(rows)
        await session.commit()


async def _complete_job(
    factory,
    job_id: str,
    celery_task_id: str,
    document_id: int,
    version: int,
    build_kind: str,
    content_sha256: str,
    categories: list[str] | tuple[str, ...],
    *,
    embedding_model: str,
    total_chunks: int,
    input_units: int,
) -> None:
    async with factory() as session:
        job = await session.scalar(
            select(KnowledgeBuildJob).where(KnowledgeBuildJob.id == job_id).with_for_update()
        )
        document = await session.scalar(
            select(KnowledgeDocument).where(KnowledgeDocument.id == document_id).with_for_update()
        )
        if (
            job is None
            or job.celery_task_id != celery_task_id
            or document is None
            or document.status in {"DELETING", "DELETED"}
            or document.version != version
        ):
            raise StaleBuildJob("document was deleted or superseded")
        job.status = "COMPLETED"
        job.stage = "COMPLETED"
        job.progress_percent = 100
        job.completed_units = job.total_units or 0
        job.completed_at = _now()
        job.heartbeat_at = job.completed_at
        job.error_summary = None
        job.content_sha256 = content_sha256
        add_aux_usage(
            session,
            event_key=f"knowledge-build:{job.id}:embedding",
            component="embedding",
            operation="document_build",
            model=embedding_model,
            user_id=job.requested_by,
            college_id=job.college_id,
            item_count=total_chunks,
            input_units=input_units,
        )
        document.dlp_categories = sorted(set(document.dlp_categories or ()) | set(categories))
        document.parse_error = None
        document.parse_status = "REVIEWED" if build_kind == "REVIEWED" else "PARSED"
        await session.commit()


async def _lock_current_document(session, document_id: int, version: int):
    document = await session.scalar(
        select(KnowledgeDocument).where(KnowledgeDocument.id == document_id).with_for_update()
    )
    if (
        document is None
        or document.status in {"DELETING", "DELETED"}
        or document.version != version
    ):
        return None
    return document


async def _ensure_job_current(
    factory,
    job_id: str,
    celery_task_id: str,
    document_id: int,
    version: int,
) -> None:
    async with factory() as session:
        await _require_current_job(session, job_id, celery_task_id, document_id, version)


async def _require_current_job(
    session,
    job_id: str,
    celery_task_id: str,
    document_id: int,
    version: int,
) -> tuple[KnowledgeBuildJob, KnowledgeDocument]:
    job = await session.scalar(
        select(KnowledgeBuildJob).where(KnowledgeBuildJob.id == job_id).with_for_update()
    )
    document = await session.scalar(
        select(KnowledgeDocument).where(KnowledgeDocument.id == document_id).with_for_update()
    )
    if (
        job is None
        or job.celery_task_id != celery_task_id
        or job.status in TERMINAL_JOB_STATUSES
        or job.version != version
        or document is None
        or document.status in {"DELETING", "DELETED"}
        or document.version != version
    ):
        raise StaleBuildJob("document was deleted or superseded")
    return job, document


async def _job_attempts(factory, job_id: str) -> int:
    async with factory() as session:
        job = await session.get(KnowledgeBuildJob, job_id)
        return int(job.attempts) if job is not None else 0


def is_transient_build_error(error: BaseException) -> bool:
    if isinstance(error, TransientBuildError):
        return True
    if "inferenceservice is not initialized" in str(error).casefold():
        # This is a deployment/configuration incompatibility, not a temporary
        # network failure. Replaying the same write cannot initialize Qdrant.
        return False
    if isinstance(error, (httpx.TimeoutException, httpx.NetworkError, SQLAlchemyError)):
        return True
    status = getattr(error, "status_code", None)
    response = getattr(error, "response", None)
    if status is None and response is not None:
        status = getattr(response, "status_code", None)
    if status in {408, 425, 429} or isinstance(status, int) and status >= 500:
        return True
    return type(error).__name__ in {
        "APIConnectionError",
        "APITimeoutError",
        "RateLimitError",
        "ServiceUnavailableError",
        "ResponseHandlingException",
        "UnexpectedResponse",
    }


def _safe_failure_summary(error: BaseException, *, permanent: bool) -> str:
    if isinstance(error, PermanentBuildError):
        return str(error)[:1000]
    if permanent:
        return "文档构建失败，请检查文件格式、内容和服务配置。"
    return "文档构建遇到暂时性服务错误，请稍后重试。"


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
