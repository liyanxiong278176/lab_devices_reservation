from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from fastapi import FastAPI
from sqlalchemy import func, select

from app.ai.config import config_fingerprint, runtime_config
from app.ai.rag.qdrant_store import QdrantKnowledgeStore
from app.ai.usage import add_aux_usage
from app.infrastructure.db.models import (
    AiEmbeddingRebuildJob,
    AiKnowledgeIndexState,
    KnowledgeChunk,
    KnowledgeDocument,
    OutboxTask,
)
from app.infrastructure.db.session import build_session_factory

BATCH_SIZE = 64


async def process_embedding_rebuild_batch(app: FastAPI, job_id: int) -> None:
    factory = getattr(app.state, "session_factory", None)
    if factory is None:
        from app.infrastructure.db.session import build_engine

        engine = build_engine(app.state.settings)
        app.state.db_engine = engine
        factory = build_session_factory(engine)
        app.state.session_factory = factory

    settings = app.state.settings
    configured_runtime = runtime_config(settings, "embedding")
    fingerprint = config_fingerprint(settings, configured_runtime)
    async with factory() as session:
        job = await session.scalar(
            select(AiEmbeddingRebuildJob)
            .where(AiEmbeddingRebuildJob.id == job_id)
            .with_for_update()
        )
        if job is None or job.status in {"COMPLETED", "ROLLED_BACK", "FAILED"}:
            return
        if not configured_runtime.api_key or fingerprint != job.config_fingerprint:
            job.status = "FAILED"
            job.error_code = "AI_EMBEDDING_ENV_CHANGED"
            job.completed_at = datetime.now(UTC).replace(tzinfo=None)
            await session.commit()
            return
        if job.status == "QUEUED":
            job.status = "RUNNING"
            job.started_at = datetime.now(UTC).replace(tzinfo=None)
            job.total_points = int(
                await session.scalar(
                    select(func.count(KnowledgeChunk.id))
                    .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
                    .where(KnowledgeDocument.status == "PUBLISHED")
                )
                or 0
            )
        rows = list(
            (
                await session.execute(
                    select(KnowledgeChunk, KnowledgeDocument)
                    .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
                    .where(
                        KnowledgeDocument.status == "PUBLISHED",
                        KnowledgeChunk.id > job.last_chunk_id,
                    )
                    .order_by(KnowledgeChunk.id)
                    .limit(BATCH_SIZE)
                )
            ).all()
        )
        session.add(job)
        await session.commit()
        target_runtime = replace(configured_runtime, collection_name=job.target_collection)

    store = QdrantKnowledgeStore(settings, target_runtime)
    try:
        await store.ensure_collection()
        if rows:
            groups: dict[int, tuple[KnowledgeDocument, list[KnowledgeChunk]]] = {}
            for chunk, document in rows:
                if document.status != "PUBLISHED":
                    continue
                group = groups.setdefault(document.id, (document, []))
                group[1].append(chunk)
            for document, chunks in groups.values():
                await store.upsert_chunks(
                    document_id=document.id,
                    title=document.title,
                    source_type=document.source_type,
                    college_id=document.college_id,
                    chunks=[item.content for item in chunks],
                    version=document.version,
                    chunk_indices=[item.chunk_index for item in chunks],
                )
            new_cursor = max(chunk.id for chunk, _document in rows)
            async with factory() as session, session.begin():
                job = await session.scalar(
                    select(AiEmbeddingRebuildJob)
                    .where(AiEmbeddingRebuildJob.id == job_id)
                    .with_for_update()
                )
                if job is None or job.status != "RUNNING":
                    return
                job.last_chunk_id = new_cursor
                job.indexed_points += sum(len(chunks) for _document, chunks in groups.values())
                next_key = f"ai-embedding-rebuild:{job.id}:{new_cursor}"
                exists = await session.scalar(
                    select(OutboxTask.id).where(OutboxTask.task_key == next_key)
                )
                if exists is None:
                    session.add(
                        OutboxTask(
                            task_key=next_key,
                            task_type="AI_EMBEDDING_REBUILD",
                            aggregate_key=f"ai-embedding-rebuild:{job.id}",
                            college_id=job.college_id,
                            payload={"job_id": job.id},
                            status="PENDING",
                            execute_at=datetime.now(UTC).replace(tzinfo=None),
                        )
                    )
            return

        count = await store.client.count(collection_name=target_runtime.collection_name, exact=True)
        if int(count.count) != int(job.total_points):
            raise RuntimeError("AI_EMBEDDING_REBUILD_POINT_COUNT_MISMATCH")
        if store.embeddings is None:
            raise RuntimeError("AI_EMBEDDING_PROVIDER_UNAVAILABLE")
        await store.embeddings.embed("实验室设备知识库索引连通性检查")

        async with factory() as session, session.begin():
            job = await session.scalar(
                select(AiEmbeddingRebuildJob)
                .where(AiEmbeddingRebuildJob.id == job_id)
                .with_for_update()
            )
            state = await session.scalar(
                select(AiKnowledgeIndexState)
                .where(AiKnowledgeIndexState.component == "embedding")
                .with_for_update()
            )
            active_collection = state.collection_name if state else settings.ai_qdrant_collection
            if (
                job is None
                or job.status != "RUNNING"
                or active_collection != job.source_collection
                or config_fingerprint(settings, runtime_config(settings, "embedding"))
                != job.config_fingerprint
            ):
                if job is not None and job.status == "RUNNING":
                    job.status = "FAILED"
                    job.error_code = "AI_EMBEDDING_CONFIG_CHANGED"
                    job.completed_at = datetime.now(UTC).replace(tzinfo=None)
                return
            if state is None:
                session.add(
                    AiKnowledgeIndexState(
                        component="embedding",
                        collection_name=job.target_collection,
                    )
                )
            else:
                state.collection_name = job.target_collection
            job.status = "COMPLETED"
            job.completed_at = datetime.now(UTC).replace(tzinfo=None)
            input_units = int(
                await session.scalar(
                    select(func.coalesce(func.sum(func.length(KnowledgeChunk.content)), 0))
                    .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
                    .where(KnowledgeDocument.status == "PUBLISHED")
                )
                or 0
            )
            add_aux_usage(
                session,
                event_key=f"embedding-rebuild:{job.id}",
                component="embedding",
                operation="blue_green_rebuild",
                model=job.target_model,
                user_id=job.requested_by,
                college_id=job.college_id,
                item_count=job.indexed_points,
                input_units=input_units,
            )
    finally:
        await store.close()
