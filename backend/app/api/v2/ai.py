from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Header, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.config import (
    AiRuntimeConfig,
    config_fingerprint,
    config_scope,
    get_component_config,
    get_runtime_config,
    runtime_config,
    validate_provider_config,
)
from app.ai.dlp import redact_text, redact_value
from app.ai.knowledge_build import (
    build_job_data,
    enqueue_knowledge_build,
    latest_build_job_data,
    latest_build_jobs,
    retry_failed_knowledge_build,
)
from app.ai.memory import (
    confirm_l2_memory,
    find_memories_forget_preview,
    invalidate_memories,
    reject_l2_memory,
)
from app.ai.providers import test_provider
from app.ai.rag.access import document_role_visible, document_scope_conditions
from app.ai.rag.qdrant_store import (
    QdrantKnowledgeStore,
    parent_context_excerpt,
    split_document_sections,
)
from app.ai.runtime import append_run_event, run_event_stream
from app.ai.schemas import (
    AiConfigData,
    AiConfigTestData,
    AiDomainTermCreateRequest,
    AiDomainTermData,
    AiEmbeddingRebuildData,
    AiEmbeddingRebuildRequest,
    ChatRequest,
    ConversationCreateRequest,
    ConversationData,
    KnowledgeBuildAcceptedData,
    KnowledgeBuildJobData,
    KnowledgeBuildSkipRequest,
    KnowledgeCreateRequest,
    KnowledgeData,
    KnowledgeReviewRequest,
    KnowledgeRoleOption,
)
from app.ai.tools.policy import TOOL_POLICIES
from app.ai.usage import (
    estimate_reservation,
    reserve_chat_tokens,
    scoped_usage,
    user_usage,
)
from app.api.v2.schemas import ReservationPlanRequest
from app.application.repairs import RepairService
from app.application.reservations import ReservationService
from app.auth.security import Principal, college_scope, get_current_principal
from app.common.response import ApiResponse
from app.core.errors import ApiError
from app.core.uploads import upload_quota_guard
from app.infrastructure.db.models import (
    AiAuxUsageEvent,
    AiCheckpoint,
    AiCheckpointWrite,
    AiConfirmation,
    AiContextSnapshot,
    AiConversation,
    AiDomainTerm,
    AiEmbeddingRebuildJob,
    AiKnowledgeIndexState,
    AiMemory,
    AiMessage,
    AiRun,
    AiRunEvent,
    AiUsageBucket,
    AiUsageEvent,
    College,
    Device,
    KnowledgeBuildJob,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSection,
    Lab,
    OutboxTask,
    Role,
    UploadAsset,
)
from app.infrastructure.db.session import get_db


async def require_ai_access(
    principal: Principal = Depends(get_current_principal),
) -> None:
    if not principal.has_permission("ai:use"):
        raise ApiError("FORBIDDEN", "当前账号没有使用 AI 工作台的权限", 403)


router = APIRouter(dependencies=[Depends(require_ai_access)])
logger = logging.getLogger(__name__)


def _ai_json_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@router.post("/ai/memories/{memory_id}/confirm")
async def confirm_ai_memory(
    memory_id: int,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    memory = await confirm_l2_memory(
        session,
        user_id=principal.user_id,
        memory_id=memory_id,
    )
    if memory is None:
        raise ApiError("AI_MEMORY_NOT_FOUND", "记忆候选不存在或已处理", 404)
    await session.commit()
    return ApiResponse.ok({"id": memory.id, "status": memory.status})


@router.post("/ai/memories/{memory_id}/reject")
async def reject_ai_memory(
    memory_id: int,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    memory = await reject_l2_memory(
        session,
        user_id=principal.user_id,
        memory_id=memory_id,
    )
    if memory is None:
        raise ApiError("AI_MEMORY_NOT_FOUND", "记忆候选不存在或已处理", 404)
    await session.commit()
    return ApiResponse.ok({"id": memory.id, "status": memory.status})


@router.get("/ai/domain-terms", response_model=ApiResponse[list[AiDomainTermData]])
async def list_ai_domain_terms(
    college_id: int | None = Query(default=None, gt=0),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[list[AiDomainTermData]]:
    if not principal.is_lab_admin and not principal.is_system_admin:
        raise ApiError("FORBIDDEN", "无权管理 AI 领域词典", 403)
    if not principal.is_system_admin and principal.college_id is None:
        raise ApiError("FORBIDDEN", "负责人账号未绑定学院，不能维护学院词典", 403)
    conditions = [AiDomainTerm.status == "APPROVED"]
    if principal.is_system_admin:
        if college_id is not None:
            conditions.append(
                or_(AiDomainTerm.college_id.is_(None), AiDomainTerm.college_id == college_id)
            )
    else:
        conditions.append(
            or_(
                AiDomainTerm.college_id.is_(None),
                AiDomainTerm.college_id == principal.college_id,
            )
        )
    rows = list(
        (
            await session.scalars(
                select(AiDomainTerm).where(*conditions).order_by(AiDomainTerm.term, AiDomainTerm.id)
            )
        ).all()
    )
    return ApiResponse.ok(
        [
            AiDomainTermData(
                id=row.id,
                college_id=row.college_id,
                term=row.term,
                canonical=row.canonical,
                kind=row.kind,
                status=row.status,
            )
            for row in rows
        ]
    )


@router.post("/ai/domain-terms", response_model=ApiResponse[AiDomainTermData], status_code=201)
async def create_ai_domain_term(
    payload: AiDomainTermCreateRequest,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[AiDomainTermData]:
    if not principal.is_lab_admin and not principal.is_system_admin:
        raise ApiError("FORBIDDEN", "无权管理 AI 领域词典", 403)
    if not principal.is_system_admin and principal.college_id is None:
        raise ApiError("FORBIDDEN", "负责人账号未绑定学院，不能维护学院词典", 403)
    term = payload.term.strip()
    canonical = payload.canonical.strip() if payload.canonical else None
    if not term or (payload.kind == "SYNONYM" and not canonical):
        raise ApiError("AI_DOMAIN_TERM_INVALID", "同义词类型必须填写标准词", 422)
    scope = payload.college_id if principal.is_system_admin else principal.college_id
    conditions = [
        func.lower(AiDomainTerm.term) == term.casefold(),
        AiDomainTerm.kind == payload.kind,
        AiDomainTerm.college_id.is_(None) if scope is None else AiDomainTerm.college_id == scope,
    ]
    if await session.scalar(select(AiDomainTerm.id).where(*conditions).limit(1)) is not None:
        raise ApiError("AI_DOMAIN_TERM_EXISTS", "该范围内已存在相同词条", 409)
    row = AiDomainTerm(
        college_id=scope,
        term=term,
        canonical=canonical if payload.kind == "SYNONYM" else None,
        kind=payload.kind,
        status="APPROVED",
        created_by=principal.user_id,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return ApiResponse.ok(
        AiDomainTermData(
            id=row.id,
            college_id=row.college_id,
            term=row.term,
            canonical=row.canonical,
            kind=row.kind,
            status=row.status,
        )
    )


@router.delete("/ai/domain-terms/{term_id}")
async def delete_ai_domain_term(
    term_id: int,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    if not principal.is_lab_admin and not principal.is_system_admin:
        raise ApiError("FORBIDDEN", "无权管理 AI 领域词典", 403)
    if not principal.is_system_admin and principal.college_id is None:
        raise ApiError("FORBIDDEN", "负责人账号未绑定学院，不能维护学院词典", 403)
    conditions = [AiDomainTerm.id == term_id]
    if not principal.is_system_admin:
        conditions.append(AiDomainTerm.college_id == principal.college_id)
    row = await session.scalar(select(AiDomainTerm).where(*conditions).with_for_update())
    if row is None:
        raise ApiError("AI_DOMAIN_TERM_NOT_FOUND", "词条不存在或无权删除", 404)
    await session.delete(row)
    await session.commit()
    return ApiResponse.ok({"id": term_id, "deleted": True})


@router.get("/ai/status")
async def get_ai_status(
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    settings = request.app.state.settings
    chat = await get_runtime_config(session, principal, settings)
    embedding = await get_component_config(session, settings, "embedding")
    chat_ready = bool(chat and chat.enabled and chat.api_key)
    embedding_ready = bool(embedding and embedding.enabled and embedding.api_key)
    missing = []
    if not chat_ready:
        missing.append("聊天模型")
    if not embedding_ready:
        missing.append("知识检索模型")
    return ApiResponse.ok(
        {
            "available": chat_ready and embedding_ready,
            "chat_configured": chat_ready,
            "embedding_configured": embedding_ready,
            "message": "AI 服务已就绪" if not missing else f"尚未配置：{'、'.join(missing)}",
        }
    )


def _conversation_data(conversation: AiConversation) -> ConversationData:
    return ConversationData(
        id=conversation.id,
        title=conversation.title,
        status=conversation.status,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


async def _load_conversation(
    session: AsyncSession,
    principal: Principal,
    conversation_id: int,
    *,
    for_update: bool = False,
) -> AiConversation:
    conditions = [AiConversation.id == conversation_id, AiConversation.user_id == principal.user_id]
    scope = college_scope(principal)
    if scope is not None:
        conditions.append(AiConversation.college_id == scope)
    query = select(AiConversation).where(*conditions)
    if for_update:
        query = query.with_for_update()
    conversation = await session.scalar(query)
    if conversation is None:
        raise ApiError("CONVERSATION_NOT_FOUND", "对话不存在或无权访问", 404)
    return conversation


@router.post("/ai/conversations", response_model=ApiResponse[ConversationData], status_code=201)
async def create_conversation(
    payload: ConversationCreateRequest,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ConversationData]:
    conversation = AiConversation(
        user_id=principal.user_id,
        college_id=principal.college_id,
        title=(payload.title or "新对话").strip()[:200] or "新对话",
        graph_thread_id=uuid4().hex,
        status="ACTIVE",
    )
    session.add(conversation)
    await session.commit()
    # MySQL server defaults are marked expired until explicitly refreshed.
    # Accessing them directly from an AsyncSession would trigger implicit IO
    # during response serialization and raise MissingGreenlet.
    await session.refresh(conversation)
    return ApiResponse.ok(_conversation_data(conversation))


@router.get("/ai/conversations", response_model=ApiResponse[list[ConversationData]])
async def list_conversations(
    limit: int = Query(default=50, ge=1, le=100),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[list[ConversationData]]:
    conditions = [AiConversation.user_id == principal.user_id]
    scope = college_scope(principal)
    if scope is not None:
        conditions.append(AiConversation.college_id == scope)
    rows = list(
        (
            await session.scalars(
                select(AiConversation)
                .where(*conditions)
                .order_by(AiConversation.updated_at.desc(), AiConversation.id.desc())
                .limit(limit)
            )
        ).all()
    )
    return ApiResponse.ok([_conversation_data(row) for row in rows])


@router.get("/ai/conversations/{conversation_id}/active-run")
async def get_active_conversation_run(
    conversation_id: int,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any] | None]:
    await _load_conversation(session, principal, conversation_id)
    run = await session.scalar(
        select(AiRun)
        .where(
            AiRun.conversation_id == conversation_id,
            AiRun.user_id == principal.user_id,
            AiRun.status.in_(["QUEUED", "RUNNING"]),
        )
        .order_by(AiRun.id.desc())
        .limit(1)
    )
    return ApiResponse.ok({"run_id": run.id, "status": run.status} if run is not None else None)


@router.delete("/ai/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    conversation = await _load_conversation(
        session,
        principal,
        conversation_id,
        for_update=True,
    )
    runs = list(
        (await session.scalars(select(AiRun).where(AiRun.conversation_id == conversation.id))).all()
    )
    if any(run.status in {"QUEUED", "RUNNING"} for run in runs):
        raise ApiError("AI_RUN_ACTIVE", "对话仍有执行中的任务，请停止或等待任务完成后再删除", 409)
    run_ids = [run.id for run in runs]
    if run_ids:
        thread_ids = [f"{conversation.graph_thread_id}:{run_id}" for run_id in run_ids]
        await session.execute(
            delete(AiCheckpointWrite).where(AiCheckpointWrite.thread_id.in_(thread_ids))
        )
        await session.execute(delete(AiCheckpoint).where(AiCheckpoint.thread_id.in_(thread_ids)))
        await session.execute(delete(AiRunEvent).where(AiRunEvent.run_id.in_(run_ids)))
        await session.execute(delete(AiUsageEvent).where(AiUsageEvent.run_id.in_(run_ids)))
        await session.execute(delete(AiConfirmation).where(AiConfirmation.run_id.in_(run_ids)))
        await session.execute(delete(AiRun).where(AiRun.id.in_(run_ids)))
        await session.execute(
            delete(OutboxTask).where(
                OutboxTask.task_key.in_([f"ai-run:{item}" for item in run_ids])
            )
        )
    await session.execute(delete(AiMessage).where(AiMessage.conversation_id == conversation.id))
    await session.delete(conversation)
    await session.commit()
    return ApiResponse.ok({"conversation_id": conversation_id, "deleted": True})


@router.get(
    "/ai/conversations/{conversation_id}/messages",
    response_model=ApiResponse[list[dict[str, Any]]],
)
async def list_messages(
    conversation_id: int,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[list[dict[str, Any]]]:
    await _load_conversation(session, principal, conversation_id)
    rows = list(
        (
            await session.scalars(
                select(AiMessage)
                .where(
                    AiMessage.conversation_id == conversation_id,
                    AiMessage.user_id == principal.user_id,
                )
                .order_by(AiMessage.created_at, AiMessage.id)
            )
        ).all()
    )

    # A confirmation preview is stored with the assistant message so a page
    # refresh can restore an unfinished action.  Do not resurrect a card after
    # the durable confirmation has already been executed, cancelled, failed,
    # or expired.  The old implementation treated every historical preview as
    # PENDING, which made a processed action look blocked forever in the UI.
    pending_ids: set[int] = set()
    for row in rows:
        metadata = row.metadata_json or {}
        pending = metadata.get("pending_confirmation") if isinstance(metadata, dict) else None
        if isinstance(pending, dict):
            try:
                confirmation_id = int(pending.get("confirmation_id", 0))
            except (TypeError, ValueError):
                confirmation_id = 0
            if confirmation_id > 0:
                pending_ids.add(confirmation_id)

    active_pending_ids: set[int] = set()
    if pending_ids:
        now = datetime.now(UTC).replace(tzinfo=None)
        confirmations = list(
            (
                await session.scalars(
                    select(AiConfirmation).where(
                        AiConfirmation.id.in_(pending_ids),
                        AiConfirmation.user_id == principal.user_id,
                        AiConfirmation.status == "PENDING",
                        AiConfirmation.expires_at > now,
                    )
                )
            ).all()
        )
        active_pending_ids = {confirmation.id for confirmation in confirmations}

    memory_candidate_ids: set[int] = set()
    for row in rows:
        metadata = row.metadata_json or {}
        candidates = metadata.get("memory_candidates", []) if isinstance(metadata, dict) else []
        for candidate in candidates:
            if isinstance(candidate, dict) and str(candidate.get("id", "")).isdigit():
                memory_candidate_ids.add(int(candidate["id"]))
    memory_statuses: dict[int, str] = {}
    if memory_candidate_ids:
        memory_rows = list(
            (
                await session.scalars(
                    select(AiMemory).where(
                        AiMemory.id.in_(memory_candidate_ids),
                        AiMemory.user_id == principal.user_id,
                    )
                )
            ).all()
        )
        memory_statuses = {memory.id: memory.status for memory in memory_rows}

    def message_metadata(row: AiMessage) -> dict[str, Any]:
        metadata = dict(row.metadata_json or {})
        candidates = metadata.get("memory_candidates")
        if isinstance(candidates, list):
            metadata["memory_candidates"] = [
                {**candidate, "status": memory_statuses.get(int(candidate.get("id", 0)), "INVALID")}
                for candidate in candidates
                if isinstance(candidate, dict)
            ]
        pending = metadata.get("pending_confirmation")
        if isinstance(pending, dict):
            try:
                confirmation_id = int(pending.get("confirmation_id", 0))
            except (TypeError, ValueError):
                confirmation_id = 0
            if confirmation_id not in active_pending_ids:
                metadata.pop("pending_confirmation", None)
        return metadata

    return ApiResponse.ok(
        [
            {
                "id": row.id,
                "role": row.role,
                "content": row.content,
                "metadata": message_metadata(row),
                "created_at": row.created_at,
            }
            for row in rows
        ]
    )


@router.get("/ai/citations/knowledge/{point_id}")
async def get_knowledge_citation(
    point_id: str,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    row = (
        await session.execute(
            select(KnowledgeChunk, KnowledgeDocument, KnowledgeSection)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .outerjoin(KnowledgeSection, KnowledgeSection.id == KnowledgeChunk.parent_section_id)
            .where(
                KnowledgeChunk.point_id == point_id,
                KnowledgeDocument.status == "PUBLISHED",
                *document_scope_conditions(principal),
            )
        )
    ).first()
    if row is None:
        raise ApiError("AI_CITATION_NOT_FOUND", "引用内容不存在或已下架", 404)
    chunk, document, section = row
    if not document_role_visible(document.allowed_roles, principal):
        raise ApiError("AI_CITATION_NOT_FOUND", "引用内容不存在或无权查看", 404)
    return ApiResponse.ok(
        {
            "citation_id": chunk.point_id,
            "document_id": document.id,
            "document_version": document.version,
            "title": document.title,
            "source_type": document.source_type,
            "section": section.section_path
            if section is not None
            else (chunk.metadata_json or {}).get("section", f"片段 {chunk.chunk_index + 1}"),
            "content": redact_text(
                parent_context_excerpt(section.content, chunk.content)
                if section is not None
                else chunk.content
            ).text,
            "chunk_content": redact_text(chunk.content).text,
        }
    )


@router.get("/ai/citations/business/{citation_id:path}")
async def get_business_citation(
    citation_id: str,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    parts = citation_id.split(":")
    if len(parts) < 3 or parts[0] != "business":
        raise ApiError("AI_CITATION_NOT_FOUND", "引用格式无效", 404)
    _, entity, raw_id, *extra = parts
    try:
        entity_id = int(raw_id)
    except ValueError as exc:
        raise ApiError("AI_CITATION_NOT_FOUND", "引用格式无效", 404) from exc
    service = ReservationService(session, principal)
    if entity == "device":
        if not principal.has_permission("device:read"):
            raise ApiError("AI_CITATION_NOT_FOUND", "引用内容不存在或无权查看", 404)
        device = await service._load_device(entity_id)
        detail = {
            "id": device.id,
            "name": device.name,
            "asset_code": device.asset_code,
            "status": device.status,
            "model": device.model,
            "lab_name": device.lab.name if device.lab else None,
        }
        title = f"设备 · {device.name}"
    elif entity == "reservation":
        reservation = await service.get_reservation(entity_id)
        detail = reservation.model_dump(mode="json")
        title = f"预约 #{reservation.id} · {reservation.device_name}"
    elif entity == "availability" and len(extra) == 2:
        if not principal.has_permission("device:read"):
            raise ApiError("AI_CITATION_NOT_FOUND", "引用内容不存在或无权查看", 404)
        from datetime import date as date_type

        try:
            start_date = date_type.fromisoformat(extra[0])
            end_date = date_type.fromisoformat(extra[1])
        except ValueError as exc:
            raise ApiError("AI_CITATION_NOT_FOUND", "引用日期格式无效", 404) from exc
        if end_date < start_date or (end_date - start_date).days > 366:
            raise ApiError("AI_CITATION_NOT_FOUND", "引用日期范围无效", 404)
        device = await service._load_device(entity_id)
        days = await service.availability(entity_id, start_date, end_date)
        detail = {
            "device_id": entity_id,
            "device_name": device.name,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "days": [item.model_dump(mode="json") for item in days],
        }
        title = f"设备可用性 · {device.name}"
    else:
        raise ApiError("AI_CITATION_NOT_FOUND", "引用内容不存在或已失效", 404)
    return ApiResponse.ok(
        {
            "citation_id": citation_id,
            "title": title,
            "source_type": "BUSINESS",
            "section": entity,
            "document_version": 0,
            "content": json.dumps(detail, ensure_ascii=False, indent=2),
        }
    )


@router.post("/ai/conversations/{conversation_id}/stream")
async def stream_message(
    conversation_id: int,
    payload: ChatRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
):
    settings = request.app.state.settings
    redaction = redact_text(payload.content.strip())
    content = redaction.text
    if not content:
        raise ApiError("AI_INPUT_EMPTY", "请输入问题或任务", 422)
    if len(content) > settings.ai_max_input_chars:
        raise ApiError("AI_INPUT_TOO_LARGE", "输入内容过长", 422)
    conversation = await _load_conversation(
        session,
        principal,
        conversation_id,
        for_update=True,
    )
    runtime = await get_runtime_config(session, principal, settings)
    embedding = await get_component_config(session, settings, "embedding")
    if runtime is None or not runtime.enabled or not runtime.api_key:
        raise ApiError(
            "AI_NOT_CONFIGURED",
            "聊天模型尚未配置，请联系系统管理员检查根目录 .env 并重启服务",
            503,
        )
    if embedding is None or not embedding.enabled or not embedding.api_key:
        raise ApiError(
            "AI_RAG_NOT_CONFIGURED",
            "知识检索模型尚未配置，请联系系统管理员检查根目录 .env 中的 Embedding Key",
            503,
        )
    run = AiRun(
        run_key=uuid4().hex,
        conversation_id=conversation.id,
        user_id=principal.user_id,
        college_id=principal.college_id,
        status="QUEUED",
        input_text=content,
    )
    session.add(run)
    conversation.updated_at = datetime.now(UTC).replace(tzinfo=None)
    session.add(
        AiMessage(
            conversation_id=conversation.id,
            user_id=principal.user_id,
            college_id=principal.college_id,
            role="user",
            content=content,
            metadata_json={
                "run_key": run.run_key,
                "redacted_categories": list(redaction.categories),
            },
        )
    )
    await session.flush()
    if redaction.categories:
        session.add(
            AiRunEvent(
                run_id=run.id,
                sequence=1,
                event_type="dlp_notice",
                payload={
                    "type": "dlp_notice",
                    "categories": list(redaction.categories),
                    "redacted_content": content,
                    "message": "为保护隐私，输入中的敏感信息已在保存和发送给模型前脱敏。",
                },
            )
        )
    reservation_tokens = estimate_reservation(
        content,
        max_output_tokens=settings.ai_max_output_tokens,
        context_documents=settings.ai_max_context_documents,
    )
    await reserve_chat_tokens(
        session,
        settings=settings,
        run_id=run.id,
        user_id=principal.user_id,
        college_id=principal.college_id,
        token_reservation=reservation_tokens,
    )
    session.add(
        OutboxTask(
            task_key=f"ai-run:{run.id}",
            task_type="AI_RUN",
            aggregate_key=f"ai-conversation:{conversation.id}",
            college_id=principal.college_id,
            payload={"run_id": run.id},
            status="PENDING",
            execute_at=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    await session.commit()

    async def events():
        async for chunk in run_event_stream(
            request.app,
            run_id=run.id,
            user_id=principal.user_id,
        ):
            yield chunk

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-AI-Run-ID": str(run.id),
        },
    )


@router.get("/ai/runs/{run_id}/events")
async def resume_ai_run(
    run_id: int,
    request: Request,
    after_event_id: int = Query(default=0, ge=0),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
):
    await _load_run(session, principal, run_id)
    if last_event_id and last_event_id.isdigit():
        after_event_id = max(after_event_id, int(last_event_id))

    async def events():
        async for chunk in run_event_stream(
            request.app,
            run_id=run_id,
            user_id=principal.user_id,
            after_event_id=after_event_id,
        ):
            yield chunk

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _load_run(session: AsyncSession, principal: Principal, run_id: int) -> AiRun:
    conditions = [AiRun.id == run_id, AiRun.user_id == principal.user_id]
    scope = college_scope(principal)
    if scope is not None:
        conditions.append(AiRun.college_id == scope)
    run = await session.scalar(select(AiRun).where(*conditions))
    if run is None:
        raise ApiError("AI_RUN_NOT_FOUND", "AI 任务不存在或无权访问", 404)
    return run


@router.post("/ai/runs/{run_id}/stop")
async def stop_ai_run(
    run_id: int,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    run = await _load_run(session, principal, run_id)
    if run.status in {"COMPLETED", "WAITING_CONFIRMATION", "FAILED", "CANCELLED"}:
        return ApiResponse.ok({"run_id": run_id, "status": run.status})
    result = await session.execute(
        update(AiRun)
        .where(
            AiRun.id == run_id,
            AiRun.user_id == principal.user_id,
            AiRun.status.in_(["QUEUED", "RUNNING"]),
        )
        .values(
            status="CANCELLED",
            error_code="AI_RUN_CANCELLED",
            completed_at=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    if result.rowcount:
        task = await session.scalar(
            select(OutboxTask).where(OutboxTask.task_key == f"ai-run:{run_id}")
        )
        if task is not None and task.status == "PENDING":
            task.status = "CANCELLED"
        await session.commit()
        running = getattr(request.app.state, "ai_run_tasks", {}).get(run_id)
        if running is not None and running is not asyncio.current_task():
            running.cancel()
        else:
            await append_run_event(
                request.app.state.session_factory,
                run_id,
                {"type": "done", "status": "CANCELLED", "message": "任务已停止"},
            )
    refreshed = await session.scalar(select(AiRun).where(AiRun.id == run_id))
    return ApiResponse.ok(
        {"run_id": run_id, "status": refreshed.status if refreshed else "CANCELLED"}
    )


async def _load_confirmation(
    session: AsyncSession,
    principal: Principal,
    confirmation_id: int,
) -> AiConfirmation:
    conditions = [
        AiConfirmation.id == confirmation_id,
        AiConfirmation.user_id == principal.user_id,
    ]
    scope = college_scope(principal)
    if scope is not None:
        conditions.append(AiConfirmation.college_id == scope)
    confirmation = await session.scalar(select(AiConfirmation).where(*conditions))
    if confirmation is None:
        raise ApiError("CONFIRMATION_NOT_FOUND", "确认请求不存在或无权访问", 404)
    return confirmation


@router.post(
    "/ai/confirmations/{confirmation_id}/confirm",
    response_model=ApiResponse[dict[str, Any]],
)
async def confirm_ai_action(
    confirmation_id: int,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    confirmation = await _load_confirmation(session, principal, confirmation_id)

    # Confirmation execution is intentionally idempotent.  A browser retry,
    # double click, or a lost response must not turn an already completed
    # action into a misleading 409 or attempt to create the reservation again.
    if confirmation.status == "EXECUTED":
        return ApiResponse.ok(
            {
                "confirmation_id": confirmation.id,
                "status": confirmation.status,
                "data": confirmation.result_json,
                "already_processed": True,
            }
        )
    if confirmation.status != "PENDING":
        raise ApiError("CONFIRMATION_ALREADY_HANDLED", "确认请求已经被处理", 409)
    forget_memory_action = confirmation.tool_name == "forget_ai_memories"
    if forget_memory_action:
        if not principal.has_permission("ai:use"):
            raise ApiError("FORBIDDEN", "当前账号已无权管理自己的 AI 记忆", 403)
    else:
        policy = TOOL_POLICIES.get(confirmation.tool_name)
        if policy is None or not policy.write or not policy.allowed(principal):
            raise ApiError("FORBIDDEN", "当前账号已无权执行该 AI 操作", 403)

    # Keep scalar identifiers before any downstream commit/rollback.  A
    # rollback expires ORM instances, and reading confirmation.run_id from the
    # expired object inside the error handler would cause MissingGreenlet.
    confirmation_id_value = confirmation.id
    confirmation_run_id = confirmation.run_id
    now = datetime.now(UTC).replace(tzinfo=None)
    if confirmation.expires_at <= now:
        confirmation.status = "EXPIRED"
        await session.commit()
        raise ApiError("CONFIRMATION_EXPIRED", "确认已过期，请重新发起操作", 409)
    result = await session.execute(
        update(AiConfirmation)
        .where(
            AiConfirmation.id == confirmation_id,
            AiConfirmation.user_id == principal.user_id,
            AiConfirmation.status == "PENDING",
            AiConfirmation.expires_at > now,
        )
        .values(status="CONFIRMED")
    )
    if result.rowcount != 1:
        raise ApiError("CONFIRMATION_ALREADY_HANDLED", "确认请求已经被处理", 409)
    args = dict(confirmation.arguments_json or {})

    async def require_current_preview(preview: dict[str, Any]) -> None:
        safe_preview, _ = redact_value(preview)
        current_hash = _ai_json_hash(safe_preview)
        stored_hash = confirmation.preview_hash or _ai_json_hash(confirmation.preview_json or {})
        if current_hash == stored_hash:
            return
        confirmation.status = "PENDING"
        confirmation.preview_json = safe_preview
        confirmation.preview_hash = current_hash
        await session.commit()
        raise ApiError(
            "AI_CONFIRMATION_PREVIEW_CHANGED",
            "操作目标或影响已变化，请核对更新后的预览再确认一次",
            409,
            data={
                "confirmation_id": confirmation.id,
                "status": "PENDING",
                "preview": safe_preview,
            },
        )

    try:
        if forget_memory_action:
            topic = str(args.get("topic", "")).strip()
            if not topic:
                raise ApiError("AI_MEMORY_TOPIC_REQUIRED", "记忆主题缺失，请重新发起", 409)
            matches = await find_memories_forget_preview(
                session,
                user_id=principal.user_id,
                topic=topic,
            )
            refreshed_preview = [
                {
                    "id": memory.id,
                    "level": memory.level,
                    "scenario": memory.scenario,
                    "content": redact_text(memory.content).text,
                }
                for memory in matches
            ]
            refreshed_args = {
                "memory_ids": [memory.id for memory in matches],
                "source_message_ids": sorted(
                    {
                        message_id
                        for memory in matches
                        for message_id in (memory.source_message_ids or [])
                    }
                ),
                "topic": topic,
            }
            safe_preview = {"topic": topic, "matches": refreshed_preview}
            current_hash = _ai_json_hash(safe_preview)
            stored_hash = confirmation.preview_hash or _ai_json_hash(
                confirmation.preview_json or {}
            )
            if current_hash != stored_hash:
                confirmation.status = "PENDING"
                confirmation.arguments_json = refreshed_args
                confirmation.arguments_hash = _ai_json_hash(refreshed_args)
                confirmation.preview_json = safe_preview
                confirmation.preview_hash = current_hash
                await session.commit()
                raise ApiError(
                    "AI_CONFIRMATION_PREVIEW_CHANGED",
                    "匹配的记忆已变化，请核对更新后的预览再确认",
                    409,
                    data={
                        "confirmation_id": confirmation.id,
                        "status": "PENDING",
                        "preview": safe_preview,
                    },
                )
            memory_ids = refreshed_args["memory_ids"]
            source_message_ids = refreshed_args["source_message_ids"]
            forgotten_count = await invalidate_memories(
                session,
                user_id=principal.user_id,
                memory_ids=memory_ids,
            )
            if source_message_ids:
                derived_conversation_ids = set(
                    await session.scalars(
                        select(AiMessage.conversation_id).where(
                            AiMessage.id.in_(source_message_ids),
                            AiMessage.user_id == principal.user_id,
                        )
                    )
                )
                snapshots = (
                    list(
                        (
                            await session.scalars(
                                select(AiContextSnapshot).where(
                                    AiContextSnapshot.user_id == principal.user_id,
                                    AiContextSnapshot.conversation_id.in_(derived_conversation_ids),
                                )
                            )
                        ).all()
                    )
                    if derived_conversation_ids
                    else []
                )
                for snapshot in snapshots:
                    # The snapshot may have compacted away its full source-ID
                    # ledger; deleting the conversation snapshot prevents the
                    # forgotten fact surviving in derived summary text.
                    await session.delete(snapshot)
            data = {
                "forgotten_count": forgotten_count,
                "raw_conversation_preserved": True,
            }
        elif confirmation.tool_name == "create_reservation":
            plan = ReservationPlanRequest(
                device_id=int(args["device_id"]),
                start_date=args["start_date"],
                end_date=args["end_date"],
                purpose=str(args.get("purpose", "实验室设备使用")),
            )
            refreshed_preview = await ReservationService(
                session,
                principal,
                max_days=request.app.state.settings.reservation_max_days,
            ).preflight(plan)
            await require_current_preview(refreshed_preview.model_dump(mode="json"))
            reservation_service = ReservationService(
                session,
                principal,
                max_days=request.app.state.settings.reservation_max_days,
            )
            execution = await reservation_service.create(
                plan,
                idempotency_key=f"ai-confirmation:{confirmation_id}",
            )
            data = execution.model_dump(mode="json")
        elif confirmation.tool_name == "cancel_reservation":
            current_reservation = await ReservationService(
                session,
                principal,
                max_days=request.app.state.settings.reservation_max_days,
            ).get_reservation(int(args["reservation_id"]))
            await require_current_preview(current_reservation.model_dump(mode="json"))
            data = (
                await ReservationService(
                    session,
                    principal,
                    max_days=request.app.state.settings.reservation_max_days,
                ).cancel(int(args["reservation_id"]))
            ).model_dump(mode="json")
        elif confirmation.tool_name == "submit_repair":
            repair_service = RepairService(session, principal)
            current_device = await ReservationService(
                session,
                principal,
                max_days=request.app.state.settings.reservation_max_days,
            )._load_device(int(args["device_id"]))
            await require_current_preview(
                {
                    "device_id": current_device.id,
                    "device_name": current_device.name,
                    "title": str(args.get("title", "设备故障报修")).strip(),
                    "description": str(args.get("description", "")).strip() or None,
                    "next_status": "MAINTENANCE",
                }
            )
            execution = await repair_service.create(
                device_id=int(args["device_id"]),
                title=str(args.get("title", "设备故障报修")),
                description=str(args.get("description", "")) or None,
                image_urls=None,
            )
            data = execution.model_dump(mode="json")
        else:
            raise ApiError("AI_TOOL_NOT_EXECUTABLE", "该 AI 操作当前不可执行", 422)
    except ApiError as exc:
        if exc.code != "AI_CONFIRMATION_PREVIEW_CHANGED":
            confirmation.status = "FAILED"
            await session.commit()
        raise
    except Exception as exc:
        # Do not leave a confirmed action permanently stuck when a downstream
        # database/provider failure occurs after the compare-and-set.
        await session.rollback()
        await session.execute(
            update(AiConfirmation)
            .where(AiConfirmation.id == confirmation_id_value)
            .values(status="FAILED", result_json={"error": "AI_ACTION_FAILED"})
        )
        await session.execute(
            update(AiRun)
            .where(AiRun.id == confirmation_run_id)
            .values(status="FAILED", error_code="AI_ACTION_FAILED")
        )
        await session.commit()
        raise ApiError("AI_ACTION_FAILED", "操作执行失败，请稍后重试", 409) from exc
    confirmation.status = "EXECUTED"
    confirmation.executed_at = now
    confirmation.result_json = data
    run = await session.scalar(select(AiRun).where(AiRun.id == confirmation.run_id))
    if run is not None:
        run.status = "COMPLETED"
        completion_text = (
            "已删除匹配的记忆，原始对话仍保留。"
            if forget_memory_action
            else "操作已按你的确认执行完成。"
        )
        run.output_text = completion_text
        run.completed_at = now
        session.add(
            AiMessage(
                conversation_id=confirmation.conversation_id,
                user_id=principal.user_id,
                college_id=principal.college_id,
                role="assistant",
                content=completion_text,
                metadata_json={"confirmation_id": confirmation.id, "result": data},
            )
        )
    await session.commit()
    return ApiResponse.ok(
        {"confirmation_id": confirmation.id, "status": confirmation.status, "data": data}
    )


@router.post(
    "/ai/confirmations/{confirmation_id}/cancel",
    response_model=ApiResponse[dict[str, Any]],
)
async def cancel_ai_action(
    confirmation_id: int,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    confirmation = await _load_confirmation(session, principal, confirmation_id)
    result = await session.execute(
        update(AiConfirmation)
        .where(
            AiConfirmation.id == confirmation_id,
            AiConfirmation.user_id == principal.user_id,
            AiConfirmation.status == "PENDING",
        )
        .values(status="CANCELLED")
    )
    if result.rowcount != 1:
        raise ApiError("CONFIRMATION_ALREADY_HANDLED", "确认请求已经被处理", 409)
    await session.execute(
        update(AiRun).where(AiRun.id == confirmation.run_id).values(status="CANCELLED")
    )
    await session.commit()
    return ApiResponse.ok({"confirmation_id": confirmation_id, "status": "CANCELLED"})


@router.get("/ai/config", response_model=ApiResponse[AiConfigData])
async def get_ai_config(
    request: Request,
    principal: Principal = Depends(get_current_principal),
) -> ApiResponse[AiConfigData]:
    config_scope(principal)
    settings = request.app.state.settings
    return ApiResponse.ok(_config_data(settings, "chat", runtime_config(settings, "chat")))


@router.get("/ai/config/components", response_model=ApiResponse[list[AiConfigData]])
async def list_ai_configs(
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[list[AiConfigData]]:
    config_scope(principal)
    settings = request.app.state.settings
    configs = []
    for component in ("chat", "embedding", "mineru"):
        runtime = (
            await get_component_config(session, settings, component)
            if component == "embedding"
            else runtime_config(settings, component)
        )
        configs.append(_config_data(settings, component, runtime))
    return ApiResponse.ok(configs)


def _config_data(settings: Any, component: str, runtime: AiRuntimeConfig) -> AiConfigData:
    configured = bool(runtime.enabled and runtime.api_key)
    return AiConfigData(
        component=component,
        scope="environment",
        source="environment" if configured else "missing",
        provider=runtime.provider,
        model=runtime.model,
        base_url=runtime.base_url,
        configured=configured,
        enabled=runtime.enabled,
        daily_quota=settings.ai_global_daily_token_cap if component == "chat" else 0,
        user_daily_token_cap=settings.ai_user_daily_token_cap if component == "chat" else 0,
        college_daily_token_cap=settings.ai_college_daily_token_cap if component == "chat" else 0,
        global_daily_token_cap=settings.ai_global_daily_token_cap if component == "chat" else 0,
        last_tested_at=None,
    )


@router.post(
    "/ai/config/{component}/test",
    response_model=ApiResponse[AiConfigTestData],
)
async def test_ai_config(
    component: str,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[AiConfigTestData]:
    config_scope(principal)
    runtime = await get_component_config(session, request.app.state.settings, component)
    validate_provider_config(
        request.app.state.settings,
        model=runtime.model,
        base_url=runtime.base_url,
        component=component,
    )
    result = await test_provider(
        component,
        runtime,
        request.app.state.settings,
    )
    return ApiResponse.ok(
        AiConfigTestData(
            component=component,
            success=result.success,
            message=result.message,
            model=runtime.model,
            latency_ms=result.latency_ms,
        )
    )


@router.get("/ai/usage")
async def get_ai_usage(
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    from app.ai.usage import usage_day

    settings = request.app.state.settings
    result: dict[str, Any] = {"mine": await user_usage(session, principal.user_id, settings)}
    auxiliary_query = select(
        AiAuxUsageEvent.component,
        AiAuxUsageEvent.operation,
        func.sum(AiAuxUsageEvent.request_count),
        func.sum(AiAuxUsageEvent.item_count),
        func.sum(AiAuxUsageEvent.input_units),
    ).where(AiAuxUsageEvent.usage_date == usage_day())
    if principal.is_system_admin:
        pass
    elif principal.is_lab_admin and principal.college_id is not None:
        auxiliary_query = auxiliary_query.where(AiAuxUsageEvent.college_id == principal.college_id)
    else:
        auxiliary_query = auxiliary_query.where(AiAuxUsageEvent.user_id == principal.user_id)
    auxiliary_rows = await session.execute(
        auxiliary_query.group_by(AiAuxUsageEvent.component, AiAuxUsageEvent.operation)
    )
    result["auxiliary"] = [
        {
            "component": row[0],
            "operation": row[1],
            "request_count": int(row[2] or 0),
            "item_count": int(row[3] or 0),
            "input_units": int(row[4] or 0),
        }
        for row in auxiliary_rows.all()
    ]
    if principal.is_lab_admin and principal.college_id is not None:
        result["college"] = {
            **await scoped_usage(
                session,
                scope_type="college",
                scope_id=principal.college_id,
            ),
            "daily_cap": settings.ai_college_daily_token_cap,
        }
    if principal.is_system_admin:
        result["global"] = {
            **await scoped_usage(session, scope_type="global", scope_id=0),
            "daily_cap": settings.ai_global_daily_token_cap,
        }
        rows = await session.execute(
            select(
                College.id,
                College.name,
                func.coalesce(AiUsageBucket.used_tokens, 0),
                func.coalesce(AiUsageBucket.reserved_tokens, 0),
            )
            .outerjoin(
                AiUsageBucket,
                (AiUsageBucket.scope_id == College.id)
                & (AiUsageBucket.scope_type == "college")
                & (AiUsageBucket.usage_date == result["mine"]["date"]),
            )
            .order_by(College.name)
        )
        result["colleges"] = [
            {
                "college_id": int(row[0]),
                "college_name": row[1],
                "used_tokens": int(row[2]),
                "reserved_tokens": int(row[3]),
                "daily_cap": settings.ai_college_daily_token_cap,
            }
            for row in rows.all()
        ]
    return ApiResponse.ok(result)


def _embedding_rebuild_data(job: AiEmbeddingRebuildJob) -> AiEmbeddingRebuildData:
    return AiEmbeddingRebuildData(
        id=job.id,
        status=job.status,
        source_collection=job.source_collection,
        target_collection=job.target_collection,
        model=job.target_model,
        total_points=job.total_points,
        indexed_points=job.indexed_points,
        error_code=job.error_code,
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


@router.post(
    "/ai/embedding/rebuild",
    response_model=ApiResponse[AiEmbeddingRebuildData],
    status_code=202,
)
async def create_embedding_rebuild(
    payload: AiEmbeddingRebuildRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[AiEmbeddingRebuildData]:
    del payload
    config_scope(principal)
    settings = request.app.state.settings
    runtime = await get_component_config(session, settings, "embedding")
    if not runtime.enabled or not runtime.api_key:
        raise ApiError("AI_EMBEDDING_NOT_CONFIGURED", "请先在根目录 .env 配置 Embedding Key", 409)
    active = await session.scalar(
        select(AiEmbeddingRebuildJob.id)
        .where(AiEmbeddingRebuildJob.status.in_(["QUEUED", "RUNNING"]))
        .limit(1)
    )
    if active is not None:
        raise ApiError("AI_EMBEDDING_REBUILD_ACTIVE", "已有向量索引重建任务正在运行", 409)

    model = runtime.model
    base_url = runtime.base_url
    validate_provider_config(settings, model=model, base_url=base_url, component="embedding")
    await test_provider(
        "embedding",
        runtime,
        settings,
    )
    source_collection = runtime.collection_name or settings.ai_qdrant_collection
    job = AiEmbeddingRebuildJob(
        job_key=uuid4().hex,
        requested_by=principal.user_id,
        college_id=principal.college_id,
        status="QUEUED",
        source_collection=source_collection,
        target_collection=f"{settings.ai_qdrant_collection}_shadow_{uuid4().hex[:12]}",
        target_model=model,
        target_base_url=base_url or "",
        source_model=model,
        source_base_url=base_url,
        config_fingerprint=config_fingerprint(settings, runtime),
    )
    session.add(job)
    await session.flush()
    session.add(
        OutboxTask(
            task_key=f"ai-embedding-rebuild:{job.id}:0",
            task_type="AI_EMBEDDING_REBUILD",
            aggregate_key=f"ai-embedding-rebuild:{job.id}",
            college_id=principal.college_id,
            payload={"job_id": job.id},
            status="PENDING",
            execute_at=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    await session.commit()
    await session.refresh(job)
    return ApiResponse.ok(_embedding_rebuild_data(job))


@router.get("/ai/embedding/rebuild/latest")
async def latest_embedding_rebuild(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[AiEmbeddingRebuildData | None]:
    config_scope(principal)
    job = await session.scalar(
        select(AiEmbeddingRebuildJob).order_by(AiEmbeddingRebuildJob.id.desc()).limit(1)
    )
    return ApiResponse.ok(_embedding_rebuild_data(job) if job is not None else None)


@router.post("/ai/embedding/rebuild/{job_id}/rollback")
async def rollback_embedding_rebuild(
    job_id: int,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[AiEmbeddingRebuildData]:
    config_scope(principal)
    settings = request.app.state.settings
    job = await session.scalar(
        select(AiEmbeddingRebuildJob).where(AiEmbeddingRebuildJob.id == job_id).with_for_update()
    )
    state = await session.scalar(
        select(AiKnowledgeIndexState)
        .where(AiKnowledgeIndexState.component == "embedding")
        .with_for_update()
    )
    if job is None:
        raise ApiError("AI_EMBEDDING_REBUILD_NOT_FOUND", "索引重建任务不存在", 404)
    runtime = runtime_config(settings, "embedding")
    if (
        job.status != "COMPLETED"
        or (state.collection_name if state else settings.ai_qdrant_collection)
        != job.target_collection
        or config_fingerprint(settings, runtime) != job.config_fingerprint
    ):
        raise ApiError("AI_EMBEDDING_ROLLBACK_UNAVAILABLE", "当前状态不支持回滚", 409)
    if state is None:
        state = AiKnowledgeIndexState(
            component="embedding",
            collection_name=job.source_collection,
        )
        session.add(state)
    else:
        state.collection_name = job.source_collection
    job.status = "ROLLED_BACK"
    await session.commit()
    await session.refresh(job)
    return ApiResponse.ok(_embedding_rebuild_data(job))


def _can_manage_knowledge(principal: Principal, college_id: int | None) -> bool:
    if principal.is_system_admin:
        return True
    scope = college_scope(principal)
    return principal.is_lab_admin and scope is not None and college_id == scope


async def _validate_knowledge_scope(
    session: AsyncSession,
    *,
    college_id: int | None,
    lab_id: int | None,
    device_id: int | None,
    allowed_roles: list[str],
) -> list[str]:
    roles = sorted({role.strip().upper() for role in allowed_roles if role.strip()})
    if len(roles) > 20:
        raise ApiError("KNOWLEDGE_SCOPE_INVALID", "可见角色不能超过 20 个", 422)
    if roles:
        existing_roles = set(
            (await session.scalars(select(Role.role_code).where(Role.role_code.in_(roles)))).all()
        )
        if existing_roles != set(roles):
            raise ApiError("KNOWLEDGE_SCOPE_INVALID", "包含系统中不存在的角色", 422)
    if (lab_id is not None or device_id is not None) and college_id is None:
        raise ApiError("KNOWLEDGE_SCOPE_INVALID", "全校知识不能绑定学院实验室或设备", 422)
    if college_id is not None:
        college_exists = await session.scalar(select(College.id).where(College.id == college_id))
        if college_exists is None:
            raise ApiError("KNOWLEDGE_SCOPE_INVALID", "指定学院不存在", 422)
    lab = None
    if lab_id is not None:
        lab = await session.get(Lab, lab_id)
        if lab is None or lab.college_id != college_id:
            raise ApiError("KNOWLEDGE_SCOPE_INVALID", "实验室不属于指定学院", 422)
    if device_id is not None:
        device = await session.get(Device, device_id)
        if device is None or device.college_id != college_id:
            raise ApiError("KNOWLEDGE_SCOPE_INVALID", "设备不属于指定学院", 422)
        if lab is not None and device.lab_id != lab.id:
            raise ApiError("KNOWLEDGE_SCOPE_INVALID", "设备不属于指定实验室", 422)
    return roles


@router.post("/ai/knowledge", response_model=ApiResponse[KnowledgeData], status_code=201)
async def create_knowledge_document(
    payload: KnowledgeCreateRequest,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[KnowledgeData]:
    if len(payload.body.strip()) < 20:
        raise ApiError(
            "DOCUMENT_TEXT_REQUIRED", "请输入至少 20 个字符的知识内容，或使用文件上传", 422
        )
    college_id = payload.college_id
    if college_id is None and not principal.is_system_admin:
        college_id = college_scope(principal)
    if not _can_manage_knowledge(principal, college_id):
        raise ApiError("FORBIDDEN", "只能维护全局或自己学院的知识库", 403)
    allowed_roles = await _validate_knowledge_scope(
        session,
        college_id=college_id,
        lab_id=payload.lab_id,
        device_id=payload.device_id,
        allowed_roles=payload.allowed_roles,
    )
    redaction = redact_text(payload.body.strip())
    safe_body = redaction.text
    document = KnowledgeDocument(
        college_id=college_id,
        lab_id=payload.lab_id,
        device_id=payload.device_id,
        allowed_roles=allowed_roles or None,
        title=payload.title.strip(),
        source_type=payload.source_type,
        body=safe_body,
        extracted_text=safe_body,
        parse_status="PARSED",
        version=1,
        status="DRAFT",
        created_by=principal.user_id,
        checksum=hashlib.sha256(safe_body.encode()).hexdigest(),
        dlp_categories=list(redaction.categories),
    )
    session.add(document)
    await session.flush()
    job = enqueue_knowledge_build(
        session,
        document,
        requested_by=principal.user_id,
        build_kind="TEXT",
    )
    await session.commit()
    await session.refresh(document)
    await session.refresh(job)
    return ApiResponse.ok(_knowledge_data(document, 0, job))


@router.post(
    "/ai/knowledge/upload",
    response_model=ApiResponse[KnowledgeBuildAcceptedData],
    status_code=202,
)
async def upload_knowledge_document(
    request: Request,
    title: str = Form(min_length=1, max_length=200),
    source_type: str = Form(default="SOP", max_length=40),
    college_id: int | None = Form(default=None, gt=0),
    lab_id: int | None = Form(default=None, gt=0),
    device_id: int | None = Form(default=None, gt=0),
    allowed_roles: list[str] = Form(default=[]),
    file: UploadFile = File(...),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[KnowledgeBuildAcceptedData]:
    if college_id is None and not principal.is_system_admin:
        college_id = college_scope(principal)
    if not _can_manage_knowledge(principal, college_id):
        raise ApiError("FORBIDDEN", "只能维护全局或自己学院的知识库", 403)
    normalized_roles = await _validate_knowledge_scope(
        session,
        college_id=college_id,
        lab_id=lab_id,
        device_id=device_id,
        allowed_roles=allowed_roles,
    )
    original_name = (file.filename or "document").replace("\\", "/").split("/")[-1]
    suffix = Path(original_name).suffix.lower()
    allowed = {
        ".pdf",
        ".doc",
        ".docx",
        ".ppt",
        ".pptx",
        ".png",
        ".jpg",
        ".jpeg",
        ".jp2",
        ".webp",
        ".gif",
        ".bmp",
    }
    if suffix not in allowed:
        raise ApiError("DOCUMENT_TYPE_NOT_ALLOWED", "仅支持 PDF、Office 文档和常见图片格式", 415)
    max_bytes = request.app.state.settings.ai_upload_max_bytes
    content = await file.read(max_bytes + 1)
    if not content or len(content) > max_bytes:
        raise ApiError(
            "DOCUMENT_TOO_LARGE", f"文件不能为空且不得超过 {max_bytes // (1024 * 1024)} MB", 413
        )
    signatures = {
        ".pdf": content.startswith(b"%PDF-"),
        ".png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        ".jpg": content.startswith(b"\xff\xd8\xff"),
        ".jpeg": content.startswith(b"\xff\xd8\xff"),
        ".gif": content.startswith((b"GIF87a", b"GIF89a")),
        ".bmp": content.startswith(b"BM"),
        ".webp": len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP",
        ".jp2": content.startswith(b"\x00\x00\x00\x0cjP  \r\n\x87\n"),
        ".doc": content.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"),
        ".ppt": content.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"),
        ".docx": content.startswith(b"PK\x03\x04"),
        ".pptx": content.startswith(b"PK\x03\x04"),
    }
    if not signatures.get(suffix, False):
        raise ApiError("DOCUMENT_SIGNATURE_INVALID", "文件扩展名与实际文件类型不匹配", 415)
    digest = hashlib.sha256(content).hexdigest()
    target_dir = Path(request.app.state.settings.upload_dir).resolve() / "ai-knowledge"
    target_dir.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    target = target_dir / f"{token}{suffix}"
    normalized_name = original_name.replace("\r", "").replace("\n", "")[:255] or "document"
    async with upload_quota_guard(
        request,
        session,
        user_id=principal.user_id,
        college_id=college_id,
        incoming_bytes=len(content),
        ai_knowledge_document=True,
    ):
        asset = UploadAsset(
            asset_token=token,
            user_id=principal.user_id,
            college_id=college_id,
            original_name=normalized_name,
            content_type=(file.content_type or "application/octet-stream")[:100],
            size_bytes=len(content),
            storage_path=str(target),
        )
        document = KnowledgeDocument(
            college_id=college_id,
            lab_id=lab_id,
            device_id=device_id,
            allowed_roles=normalized_roles or None,
            title=title.strip(),
            source_type=source_type.strip() or "SOP",
            body="",
            version=1,
            status="DRAFT",
            created_by=principal.user_id,
            checksum=digest,
            source_file_path=str(target),
            source_file_name=normalized_name,
            source_sha256=digest,
            parse_status="UPLOADED",
        )
        session.add_all([asset, document])
        try:
            await asyncio.to_thread(target.write_bytes, content)
            await session.flush()
            job = enqueue_knowledge_build(
                session,
                document,
                requested_by=principal.user_id,
                build_kind="UPLOAD",
            )
            await session.commit()
            await session.refresh(document)
            await session.refresh(job)
        except Exception:
            await session.rollback()
            await asyncio.to_thread(target.unlink, missing_ok=True)
            raise
    build_data = build_job_data(job)
    return ApiResponse.ok(
        KnowledgeBuildAcceptedData(
            document_id=document.id,
            job_id=job.id,
            task_id=job.celery_task_id,
            status=job.status,
            build_job=build_data,
        )
    )


@router.get(
    "/ai/knowledge/scope-roles",
    response_model=ApiResponse[list[KnowledgeRoleOption]],
)
async def list_knowledge_scope_roles(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[list[KnowledgeRoleOption]]:
    if not principal.is_lab_admin:
        raise ApiError("FORBIDDEN", "只有实验室负责人或系统管理员可以管理知识库", 403)
    rows = (
        await session.execute(select(Role.role_code, Role.role_name).order_by(Role.role_code))
    ).all()
    return ApiResponse.ok([KnowledgeRoleOption(code=code, name=name) for code, name in rows])


@router.get("/ai/knowledge/{document_id}")
async def get_knowledge_document(
    document_id: int,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    document = await _load_knowledge_document(session, principal, document_id)
    if not _can_manage_knowledge(principal, document.college_id):
        raise ApiError("DOCUMENT_NOT_FOUND", "知识文档不存在或无权操作", 404)
    build_job = await session.scalar(
        select(KnowledgeBuildJob)
        .where(KnowledgeBuildJob.document_id == document.id)
        .order_by(KnowledgeBuildJob.created_at.desc(), KnowledgeBuildJob.id.desc())
        .limit(1)
    )
    return ApiResponse.ok(
        {
            **_knowledge_data(document, 0, build_job).model_dump(),
            "body": document.body,
            "extracted_text": document.extracted_text,
            "reviewed_text": document.reviewed_text,
            "checksum": document.checksum,
        }
    )


async def _load_knowledge_document(
    session: AsyncSession,
    principal: Principal,
    document_id: int,
) -> KnowledgeDocument:
    document = await session.scalar(
        select(KnowledgeDocument).where(KnowledgeDocument.id == document_id)
    )
    if document is None or not _can_manage_knowledge(principal, document.college_id):
        raise ApiError("DOCUMENT_NOT_FOUND", "知识文档不存在或无权操作", 404)
    return document


@router.post(
    "/ai/knowledge/{document_id}/parse",
    response_model=ApiResponse[KnowledgeBuildAcceptedData],
    status_code=202,
)
async def parse_knowledge_document(
    document_id: int,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[KnowledgeBuildAcceptedData]:
    document = await session.scalar(
        select(KnowledgeDocument).where(KnowledgeDocument.id == document_id).with_for_update()
    )
    if document is None or not _can_manage_knowledge(principal, document.college_id):
        raise ApiError("DOCUMENT_NOT_FOUND", "知识文档不存在或无权操作", 404)
    if document.parse_status not in {"UPLOADED", "FAILED"}:
        raise ApiError("DOCUMENT_PARSE_STATE_INVALID", "文档当前状态不允许重新构建", 409)
    active_job = await session.scalar(
        select(KnowledgeBuildJob.id).where(
            KnowledgeBuildJob.document_id == document.id,
            KnowledgeBuildJob.status.in_(["QUEUED", "PROCESSING", "RETRYING"]),
        )
    )
    if active_job is not None:
        raise ApiError("DOCUMENT_BUILD_IN_PROGRESS", "当前文档已有构建任务，请稍后再提交", 409)
    if document.source_file_path:
        build_kind = "UPLOAD"
    elif document.reviewed_text:
        build_kind = "REVIEWED"
    elif document.body:
        build_kind = "TEXT"
    else:
        raise ApiError("DOCUMENT_SOURCE_MISSING", "文档没有可重新构建的来源内容", 409)
    failed_job = await session.scalar(
        select(KnowledgeBuildJob)
        .where(
            KnowledgeBuildJob.document_id == document.id,
            KnowledgeBuildJob.version == document.version,
            KnowledgeBuildJob.status == "FAILED",
        )
        .order_by(KnowledgeBuildJob.sequence)
        .limit(1)
        .with_for_update()
    )
    if failed_job is not None:
        job = retry_failed_knowledge_build(session, document, failed_job)
    else:
        job = enqueue_knowledge_build(
            session,
            document,
            requested_by=principal.user_id,
            build_kind=build_kind,
        )
    await session.commit()
    await session.refresh(document)
    await session.refresh(job)
    build_data = build_job_data(job)
    return ApiResponse.ok(
        KnowledgeBuildAcceptedData(
            document_id=document.id,
            job_id=job.id,
            task_id=job.celery_task_id,
            status=job.status,
            build_job=build_data,
        )
    )


@router.post(
    "/ai/knowledge/{document_id}/build-jobs/{job_id}/skip",
    response_model=ApiResponse[KnowledgeBuildJobData],
)
async def skip_failed_knowledge_build(
    document_id: int,
    job_id: str,
    payload: KnowledgeBuildSkipRequest,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[KnowledgeBuildJobData]:
    document = await session.scalar(
        select(KnowledgeDocument).where(KnowledgeDocument.id == document_id).with_for_update()
    )
    if document is None or not _can_manage_knowledge(principal, document.college_id):
        raise ApiError("DOCUMENT_NOT_FOUND", "知识文档不存在或无权操作", 404)
    job = await session.scalar(
        select(KnowledgeBuildJob)
        .where(
            KnowledgeBuildJob.id == job_id,
            KnowledgeBuildJob.document_id == document.id,
            KnowledgeBuildJob.college_id == document.college_id,
        )
        .with_for_update()
    )
    if job is None:
        raise ApiError("KNOWLEDGE_BUILD_NOT_FOUND", "构建任务不存在或无权操作", 404)
    if job.status != "FAILED":
        raise ApiError("KNOWLEDGE_BUILD_NOT_FAILED", "只有失败的构建任务可以跳过", 409)
    earlier_unresolved = await session.scalar(
        select(KnowledgeBuildJob.id)
        .where(
            KnowledgeBuildJob.document_id == document.id,
            KnowledgeBuildJob.sequence < job.sequence,
            KnowledgeBuildJob.status.in_(["QUEUED", "PROCESSING", "RETRYING", "FAILED"]),
        )
        .order_by(KnowledgeBuildJob.sequence)
        .limit(1)
    )
    if earlier_unresolved is not None:
        raise ApiError(
            "KNOWLEDGE_BUILD_PREDECESSOR_PENDING",
            "请先处理更早的构建任务",
            409,
        )
    now = datetime.now(UTC).replace(tzinfo=None)
    job.status = "SKIPPED"
    job.stage = "SKIPPED"
    job.skipped_by = principal.user_id
    job.skipped_at = now
    job.skip_reason = payload.reason
    job.completed_at = now
    await session.commit()
    await session.refresh(job)
    logger.info(
        "knowledge build skipped document_id=%s job_id=%s tenant_id=%s "
        "actor_id=%s reason_length=%s",
        document.id,
        job.id,
        document.college_id,
        principal.user_id,
        len(payload.reason),
    )
    return ApiResponse.ok(build_job_data(job))


@router.post(
    "/ai/knowledge/{document_id}/build-jobs/{job_id}/retry",
    response_model=ApiResponse[KnowledgeBuildAcceptedData],
    status_code=202,
)
async def retry_failed_knowledge_build_job(
    document_id: int,
    job_id: str,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[KnowledgeBuildAcceptedData]:
    document = await session.scalar(
        select(KnowledgeDocument).where(KnowledgeDocument.id == document_id).with_for_update()
    )
    if document is None or not _can_manage_knowledge(principal, document.college_id):
        raise ApiError("DOCUMENT_NOT_FOUND", "知识文档不存在或无权操作", 404)
    job = await session.scalar(
        select(KnowledgeBuildJob)
        .where(
            KnowledgeBuildJob.id == job_id,
            KnowledgeBuildJob.document_id == document.id,
            KnowledgeBuildJob.college_id == document.college_id,
        )
        .with_for_update()
    )
    if job is None:
        raise ApiError("KNOWLEDGE_BUILD_NOT_FOUND", "构建任务不存在或无权操作", 404)
    if job.status != "FAILED":
        raise ApiError("KNOWLEDGE_BUILD_NOT_FAILED", "只有失败的构建任务可以重试", 409)
    if job.version != document.version:
        raise ApiError(
            "KNOWLEDGE_BUILD_VERSION_SUPERSEDED",
            "该失败任务属于旧文档版本，请跳过它以继续后续构建",
            409,
        )
    earlier_unresolved = await session.scalar(
        select(KnowledgeBuildJob.id)
        .where(
            KnowledgeBuildJob.document_id == document.id,
            KnowledgeBuildJob.sequence < job.sequence,
            KnowledgeBuildJob.status.in_(["QUEUED", "PROCESSING", "RETRYING", "FAILED"]),
        )
        .order_by(KnowledgeBuildJob.sequence)
        .limit(1)
    )
    if earlier_unresolved is not None:
        raise ApiError(
            "KNOWLEDGE_BUILD_PREDECESSOR_PENDING",
            "请先处理更早的构建任务",
            409,
        )
    retried = retry_failed_knowledge_build(session, document, job)
    await session.commit()
    await session.refresh(retried)
    logger.info(
        "knowledge build retry requested document_id=%s job_id=%s tenant_id=%s "
        "actor_id=%s sequence=%s",
        document.id,
        retried.id,
        document.college_id,
        principal.user_id,
        retried.sequence,
    )
    data = build_job_data(retried)
    return ApiResponse.ok(
        KnowledgeBuildAcceptedData(
            document_id=document.id,
            job_id=retried.id,
            task_id=retried.celery_task_id,
            status=retried.status,
            build_job=data,
        )
    )


@router.put("/ai/knowledge/{document_id}/review", response_model=ApiResponse[KnowledgeData])
async def review_knowledge_document(
    document_id: int,
    payload: KnowledgeReviewRequest,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[KnowledgeData]:
    document = await session.scalar(
        select(KnowledgeDocument).where(KnowledgeDocument.id == document_id).with_for_update()
    )
    if document is None or not _can_manage_knowledge(principal, document.college_id):
        raise ApiError("DOCUMENT_NOT_FOUND", "知识文档不存在或无权操作", 404)
    if document.parse_status not in {"PARSED", "REVIEWED", "PUBLISHED"}:
        raise ApiError("DOCUMENT_NOT_PARSED", "请等待文档解析完成后再审核", 409)
    active_job = await session.scalar(
        select(KnowledgeBuildJob).where(
            KnowledgeBuildJob.document_id == document.id,
            KnowledgeBuildJob.status.in_(["QUEUED", "PROCESSING", "RETRYING"]),
        )
    )
    if active_job is not None:
        raise ApiError("DOCUMENT_BUILD_IN_PROGRESS", "当前文档版本仍在构建，请稍后再审核", 409)
    redaction = redact_text(payload.reviewed_text.strip())
    document.reviewed_text = redaction.text
    document.dlp_categories = sorted(set(document.dlp_categories or ()) | set(redaction.categories))
    document.reviewed_by = principal.user_id
    document.reviewed_at = datetime.now(UTC).replace(tzinfo=None)
    content_sha256 = hashlib.sha256(redaction.text.encode("utf-8")).hexdigest()
    job = await session.scalar(
        select(KnowledgeBuildJob)
        .where(
            KnowledgeBuildJob.document_id == document.id,
            KnowledgeBuildJob.version == document.version,
            KnowledgeBuildJob.status == "COMPLETED",
            KnowledgeBuildJob.content_sha256 == content_sha256,
        )
        .order_by(KnowledgeBuildJob.created_at.desc())
    )
    if job is None:
        document.version = max(document.version, document.active_version or 0) + 1
        if document.active_version is None:
            document.status = "DRAFT"
        document.parse_status = "QUEUED"
        job = enqueue_knowledge_build(
            session,
            document,
            requested_by=principal.user_id,
            build_kind="REVIEWED",
        )
    else:
        document.parse_status = "REVIEWED"
        document.parse_error = None
    await session.commit()
    await session.refresh(document)
    await session.refresh(job)
    return ApiResponse.ok(_knowledge_data(document, 0, job))


@router.get("/ai/knowledge/{document_id}/chunks/preview")
async def preview_knowledge_chunks(
    document_id: int,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[list[dict[str, Any]]]:
    document = await _load_knowledge_document(session, principal, document_id)
    content = document.reviewed_text or document.extracted_text or document.body
    sections, chunks = split_document_sections(content)
    return ApiResponse.ok(
        [
            {
                "index": chunk.index,
                "section_path": chunk.section_path,
                "parent_section_index": chunk.section_index,
                "parent_heading": sections[chunk.section_index].heading,
                "content": chunk.content,
                "characters": len(chunk.content),
            }
            for chunk in chunks
        ]
    )


@router.post("/ai/knowledge/{document_id}/publish", response_model=ApiResponse[KnowledgeData])
async def publish_knowledge_document(
    document_id: int,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[KnowledgeData]:
    document = await session.scalar(
        select(KnowledgeDocument).where(KnowledgeDocument.id == document_id).with_for_update()
    )
    if document is None or not _can_manage_knowledge(principal, document.college_id):
        raise ApiError("DOCUMENT_NOT_FOUND", "知识文档不存在或无权操作", 404)
    if document.parse_status != "REVIEWED" or not document.reviewed_text:
        raise ApiError("DOCUMENT_REVIEW_REQUIRED", "请先审核并确认提取内容，再发布到知识库", 409)
    content_sha256 = hashlib.sha256(document.reviewed_text.encode("utf-8")).hexdigest()
    build_job = await session.scalar(
        select(KnowledgeBuildJob)
        .where(
            KnowledgeBuildJob.document_id == document.id,
            KnowledgeBuildJob.version == document.version,
            KnowledgeBuildJob.status == "COMPLETED",
            KnowledgeBuildJob.content_sha256 == content_sha256,
        )
        .order_by(KnowledgeBuildJob.created_at.desc())
    )
    if build_job is None:
        raise ApiError(
            "DOCUMENT_BUILD_REQUIRED",
            "当前审核文本尚未完成向量构建，请等待任务完成后再发布",
            409,
        )
    chunk_count = int(
        await session.scalar(
            select(func.count(KnowledgeChunk.id)).where(
                KnowledgeChunk.document_id == document.id,
                KnowledgeChunk.version == document.version,
            )
        )
        or 0
    )
    if chunk_count == 0:
        raise ApiError("DOCUMENT_INDEX_EMPTY", "当前版本没有可发布的检索片段", 409)

    previous_version = document.active_version
    document.body = document.reviewed_text
    document.active_version = document.version
    document.status = "PUBLISHED"
    document.parse_status = "PUBLISHED"
    document.parse_error = None
    document.published_at = datetime.now(UTC).replace(tzinfo=None)
    if previous_version is not None and previous_version != document.version:
        await session.execute(
            delete(KnowledgeChunk).where(
                KnowledgeChunk.document_id == document.id,
                KnowledgeChunk.version != document.version,
            )
        )
        await session.execute(
            delete(KnowledgeSection).where(
                KnowledgeSection.document_id == document.id,
                KnowledgeSection.version != document.version,
            )
        )
        now = datetime.now(UTC).replace(tzinfo=None)
        session.add(
            OutboxTask(
                task_key=f"ai-knowledge-cleanup:{document.id}:keep:{document.version}",
                task_type="AI_KNOWLEDGE_CLEANUP",
                aggregate_key=f"ai-knowledge:{document.id}",
                college_id=document.college_id,
                payload={"document_id": document.id, "keep_version": document.version},
                status="PENDING",
                execute_at=now,
            )
        )
    await session.commit()
    await session.refresh(document)
    await session.refresh(build_job)
    return ApiResponse.ok(_knowledge_data(document, chunk_count, build_job))


@router.get("/ai/knowledge", response_model=ApiResponse[list[KnowledgeData]])
async def list_knowledge(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[list[KnowledgeData]]:
    if not principal.is_lab_admin:
        raise ApiError("FORBIDDEN", "只有实验室负责人或系统管理员可以管理知识库", 403)
    scope = college_scope(principal)
    conditions = []
    if scope is not None:
        conditions.append(KnowledgeDocument.college_id == scope)
    conditions.append(KnowledgeDocument.status.not_in(["DELETED", "DELETING"]))
    rows = list(
        (
            await session.scalars(
                select(KnowledgeDocument)
                .where(*conditions)
                .order_by(KnowledgeDocument.updated_at.desc())
            )
        ).all()
    )
    document_ids = [row.id for row in rows]
    jobs = await latest_build_jobs(session, document_ids)
    counts = (
        {
            int(row[0]): int(row[1])
            for row in (
                await session.execute(
                    select(KnowledgeChunk.document_id, func.count(KnowledgeChunk.id))
                    .join(
                        KnowledgeDocument,
                        KnowledgeDocument.id == KnowledgeChunk.document_id,
                    )
                    .where(
                        KnowledgeChunk.document_id.in_(document_ids),
                        KnowledgeChunk.version == KnowledgeDocument.version,
                    )
                    .group_by(KnowledgeChunk.document_id)
                )
            ).all()
        }
        if document_ids
        else {}
    )
    job_data = await latest_build_job_data(session, jobs)
    documents = []
    for row in rows:
        data = _knowledge_data(row, counts.get(row.id, 0), jobs.get(row.id))
        if row.id in job_data:
            data.build_job = job_data[row.id]
        documents.append(data)
    return ApiResponse.ok(documents)


@router.get(
    "/ai/knowledge/{document_id}/build-jobs/{job_id}",
    response_model=ApiResponse[KnowledgeBuildJobData],
)
async def get_knowledge_build_job(
    document_id: int,
    job_id: str,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[KnowledgeBuildJobData]:
    document = await _load_knowledge_document(session, principal, document_id)
    tenant_condition = (
        KnowledgeBuildJob.college_id.is_(None)
        if document.college_id is None
        else KnowledgeBuildJob.college_id == document.college_id
    )
    job = await session.scalar(
        select(KnowledgeBuildJob).where(
            KnowledgeBuildJob.id == job_id,
            KnowledgeBuildJob.document_id == document.id,
            tenant_condition,
        )
    )
    if job is None:
        raise ApiError("KNOWLEDGE_BUILD_NOT_FOUND", "构建任务不存在或无权访问", 404)
    job_data = (await latest_build_job_data(session, {document.id: job}))[document.id]
    return ApiResponse.ok(job_data)


@router.delete("/ai/knowledge/{document_id}")
async def delete_knowledge_document(
    document_id: int,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    document = await _load_knowledge_document(session, principal, document_id)
    if document.status == "DELETED":
        return ApiResponse.ok({"document_id": document.id, "deleted": True})
    document.status = "DELETING"
    await session.execute(
        update(KnowledgeBuildJob)
        .where(
            KnowledgeBuildJob.document_id == document.id,
            KnowledgeBuildJob.status.in_(["QUEUED", "PROCESSING", "RETRYING"]),
        )
        .values(
            status="CANCELLED",
            stage="CANCELLED",
            error_summary="文档已删除。",
            completed_at=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    await session.commit()

    embedding = await get_component_config(session, request.app.state.settings, "embedding")
    store = QdrantKnowledgeStore(
        request.app.state.settings,
        embedding,
        embeddings_required=False,
    )
    try:
        await store.delete_document(document.id)
    except Exception as exc:
        raise ApiError(
            "DOCUMENT_VECTOR_DELETE_FAILED",
            "知识向量暂时无法清理，请稍后重试",
            503,
        ) from exc
    finally:
        await store.close()

    if document.source_file_path:
        upload_root = (
            Path(request.app.state.settings.upload_dir).resolve() / "ai-knowledge"
        ).resolve()
        source_path = Path(document.source_file_path).resolve()
        if source_path.is_relative_to(upload_root) and source_path.is_file():
            source_path.unlink(missing_ok=True)
    await session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id))
    await session.execute(
        delete(KnowledgeSection).where(KnowledgeSection.document_id == document.id)
    )
    document.body = ""
    document.extracted_text = None
    document.reviewed_text = None
    document.source_file_path = None
    document.status = "DELETED"
    document.parse_status = "DELETED"
    document.parse_error = None
    await session.commit()
    return ApiResponse.ok({"document_id": document.id, "deleted": True})


def _knowledge_data(
    document: KnowledgeDocument,
    chunk_count: int,
    build_job: KnowledgeBuildJob | None = None,
) -> KnowledgeData:
    return KnowledgeData(
        id=document.id,
        title=document.title,
        source_type=document.source_type,
        college_id=document.college_id,
        lab_id=document.lab_id,
        device_id=document.device_id,
        allowed_roles=list(document.allowed_roles or ()),
        status=document.status,
        version=document.version,
        chunk_count=chunk_count,
        created_at=document.created_at,
        published_at=document.published_at,
        source_file_name=document.source_file_name,
        parse_status=document.parse_status,
        parse_error=document.parse_error,
        dlp_categories=list(document.dlp_categories or ()),
        build_job=build_job_data(build_job) if build_job is not None else None,
    )
