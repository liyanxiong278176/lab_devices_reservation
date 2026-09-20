from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.config import (
    config_scope,
    encrypt_api_key,
    get_runtime_config,
    validate_provider_config,
)
from app.ai.graph.harness import AgentHarness
from app.ai.rag.qdrant_store import QdrantKnowledgeStore, split_text
from app.ai.schemas import (
    AiConfigData,
    AiConfigUpdateRequest,
    ChatRequest,
    ConversationCreateRequest,
    ConversationData,
    KnowledgeCreateRequest,
    KnowledgeData,
)
from app.api.v2.schemas import ReservationPlanRequest
from app.application.repairs import RepairService
from app.application.reservations import ReservationService
from app.auth.security import Principal, college_scope, get_current_principal
from app.common.response import ApiResponse
from app.core.errors import ApiError
from app.infrastructure.cache.redis import reservation_lock
from app.infrastructure.db.models import (
    AiConfirmation,
    AiConversation,
    AiMessage,
    AiProviderConfig,
    AiRun,
    KnowledgeChunk,
    KnowledgeDocument,
)
from app.infrastructure.db.session import get_db

router = APIRouter()


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
) -> AiConversation:
    conditions = [AiConversation.id == conversation_id, AiConversation.user_id == principal.user_id]
    scope = college_scope(principal)
    if scope is not None:
        conditions.append(AiConversation.college_id == scope)
    conversation = await session.scalar(select(AiConversation).where(*conditions))
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

    def message_metadata(row: AiMessage) -> dict[str, Any]:
        metadata = dict(row.metadata_json or {})
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


@router.post("/ai/conversations/{conversation_id}/stream")
async def stream_message(
    conversation_id: int,
    payload: ChatRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
):
    settings = request.app.state.settings
    content = payload.content.strip()
    if not content:
        raise ApiError("AI_INPUT_EMPTY", "请输入问题或任务", 422)
    if len(content) > settings.ai_max_input_chars:
        raise ApiError("AI_INPUT_TOO_LARGE", "输入内容过长", 422)
    conversation = await _load_conversation(session, principal, conversation_id)
    runtime = await get_runtime_config(session, principal, settings)
    if runtime is not None and not runtime.enabled:
        raise ApiError("AI_DISABLED", "当前学院的 AI 服务已停用", 503)
    run = AiRun(
        run_key=uuid4().hex,
        conversation_id=conversation.id,
        user_id=principal.user_id,
        college_id=principal.college_id,
        status="RUNNING",
        input_text=content,
    )
    session.add(run)
    session.add(
        AiMessage(
            conversation_id=conversation.id,
            user_id=principal.user_id,
            college_id=principal.college_id,
            role="user",
            content=content,
            metadata_json={"run_key": run.run_key},
        )
    )
    await session.flush()
    await session.commit()

    harness = AgentHarness(
        session,
        principal,
        settings,
        runtime,
        run,
        conversation.graph_thread_id,
    )

    async def events():
        async for event in harness.stream():
            event_type = str(event.get("type", "message"))
            body = json.dumps(event, ensure_ascii=False, default=str)
            yield f"event: {event_type}\ndata: {body}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
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
    try:
        if confirmation.tool_name == "create_reservation":
            plan = ReservationPlanRequest(
                device_id=int(args["device_id"]),
                start_date=args["start_date"],
                end_date=args["end_date"],
                purpose=str(args.get("purpose", "实验室设备使用")),
            )
            async with reservation_lock(request, plan.device_id):
                execution = await ReservationService(
                    session,
                    principal,
                    max_days=request.app.state.settings.reservation_max_days,
                ).create(plan, idempotency_key=f"ai-confirmation:{confirmation_id}")
            data = execution.model_dump(mode="json")
        elif confirmation.tool_name == "cancel_reservation":
            data = (
                await ReservationService(
                    session,
                    principal,
                    max_days=request.app.state.settings.reservation_max_days,
                ).cancel(int(args["reservation_id"]))
            ).model_dump(mode="json")
        elif confirmation.tool_name == "submit_repair":
            execution = await RepairService(session, principal).create(
                device_id=int(args["device_id"]),
                title=str(args.get("title", "设备故障报修")),
                description=str(args.get("description", "")) or None,
                image_urls=None,
            )
            data = execution.model_dump(mode="json")
        else:
            raise ApiError("AI_TOOL_NOT_EXECUTABLE", "该 AI 操作当前不可执行", 422)
    except ApiError:
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
        run.output_text = "操作已按你的确认执行完成。"
        run.completed_at = now
        session.add(
            AiMessage(
                conversation_id=confirmation.conversation_id,
                user_id=principal.user_id,
                college_id=principal.college_id,
                role="assistant",
                content="操作已按你的确认执行完成。",
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
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[AiConfigData]:
    scope_key, _ = config_scope(principal)
    config = await session.scalar(
        select(AiProviderConfig).where(AiProviderConfig.scope_key == scope_key)
    )
    return ApiResponse.ok(
        AiConfigData(
            scope=scope_key,
            provider=config.provider if config else None,
            model=config.model if config else None,
            base_url=config.base_url if config else None,
            configured=bool(config and config.api_key_encrypted),
            enabled=config.enabled if config else False,
            daily_quota=config.daily_quota if config else 0,
        )
    )


@router.put("/ai/config", response_model=ApiResponse[AiConfigData])
async def update_ai_config(
    payload: AiConfigUpdateRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[AiConfigData]:
    scope_key, college_id = config_scope(principal)
    settings = request.app.state.settings
    validate_provider_config(settings, model=payload.model, base_url=payload.base_url)
    config = await session.scalar(
        select(AiProviderConfig).where(AiProviderConfig.scope_key == scope_key)
    )
    if config is None:
        config = AiProviderConfig(
            scope_key=scope_key,
            college_id=college_id,
            provider=payload.provider,
            model=payload.model,
            base_url=payload.base_url,
            api_key_encrypted=encrypt_api_key(settings, payload.api_key)
            if payload.api_key
            else None,
            enabled=payload.enabled,
            daily_quota=payload.daily_quota,
        )
        session.add(config)
    else:
        config.provider = payload.provider
        config.model = payload.model
        config.base_url = payload.base_url
        if payload.api_key:
            config.api_key_encrypted = encrypt_api_key(settings, payload.api_key)
        config.enabled = payload.enabled
        config.daily_quota = payload.daily_quota
    await session.commit()
    return ApiResponse.ok(
        AiConfigData(
            scope=scope_key,
            provider=config.provider,
            model=config.model,
            base_url=config.base_url,
            configured=bool(config.api_key_encrypted),
            enabled=config.enabled,
            daily_quota=config.daily_quota,
        )
    )


def _can_manage_knowledge(principal: Principal, college_id: int | None) -> bool:
    if principal.is_system_admin:
        return True
    scope = college_scope(principal)
    return principal.is_lab_admin and scope is not None and college_id == scope


@router.post("/ai/knowledge", response_model=ApiResponse[KnowledgeData], status_code=201)
async def create_knowledge_document(
    payload: KnowledgeCreateRequest,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[KnowledgeData]:
    college_id = payload.college_id
    if college_id is None and not principal.is_system_admin:
        college_id = college_scope(principal)
    if not _can_manage_knowledge(principal, college_id):
        raise ApiError("FORBIDDEN", "只能维护全局或自己学院的知识库", 403)
    document = KnowledgeDocument(
        college_id=college_id,
        title=payload.title.strip(),
        source_type=payload.source_type,
        body=payload.body.strip(),
        version=1,
        status="DRAFT",
        created_by=principal.user_id,
        checksum=hashlib.sha256(payload.body.encode()).hexdigest(),
    )
    session.add(document)
    await session.commit()
    await session.refresh(document)
    return ApiResponse.ok(_knowledge_data(document, 0))


@router.post("/ai/knowledge/{document_id}/publish", response_model=ApiResponse[KnowledgeData])
async def publish_knowledge_document(
    document_id: int,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[KnowledgeData]:
    document = await session.scalar(
        select(KnowledgeDocument).where(KnowledgeDocument.id == document_id)
    )
    if document is None or not _can_manage_knowledge(principal, document.college_id):
        raise ApiError("DOCUMENT_NOT_FOUND", "知识文档不存在或无权操作", 404)
    runtime = await get_runtime_config(session, principal, request.app.state.settings)
    store = QdrantKnowledgeStore(request.app.state.settings, runtime)
    try:
        chunks = split_text(document.body)
        point_ids = await store.upsert_chunks(
            document_id=document.id,
            title=document.title,
            source_type=document.source_type,
            college_id=document.college_id,
            chunks=chunks,
        )
    finally:
        await store.close()
    await session.execute(
        KnowledgeChunk.__table__.delete().where(KnowledgeChunk.document_id == document.id)
    )
    for index, (point_id, content) in enumerate(zip(point_ids, chunks, strict=True)):
        session.add(
            KnowledgeChunk(
                document_id=document.id,
                college_id=document.college_id,
                point_id=point_id,
                chunk_index=index,
                content=content,
                metadata_json={"title": document.title, "source_type": document.source_type},
            )
        )
    document.status = "PUBLISHED"
    document.published_at = datetime.now(UTC).replace(tzinfo=None)
    await session.commit()
    return ApiResponse.ok(_knowledge_data(document, len(chunks)))


@router.get("/ai/knowledge", response_model=ApiResponse[list[KnowledgeData]])
async def list_knowledge(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[list[KnowledgeData]]:
    scope = college_scope(principal)
    conditions = []
    if scope is not None:
        conditions.append(KnowledgeDocument.college_id.in_([None, scope]))
    rows = list(
        (
            await session.scalars(
                select(KnowledgeDocument)
                .where(*conditions)
                .order_by(KnowledgeDocument.updated_at.desc())
            )
        ).all()
    )
    counts = {
        int(row[0]): int(row[1])
        for row in (
            await session.execute(
                select(KnowledgeChunk.document_id, func.count(KnowledgeChunk.id)).group_by(
                    KnowledgeChunk.document_id
                )
            )
        ).all()
    }
    return ApiResponse.ok([_knowledge_data(row, counts.get(row.id, 0)) for row in rows])


def _knowledge_data(document: KnowledgeDocument, chunk_count: int) -> KnowledgeData:
    return KnowledgeData(
        id=document.id,
        title=document.title,
        source_type=document.source_type,
        college_id=document.college_id,
        status=document.status,
        version=document.version,
        chunk_count=chunk_count,
        created_at=document.created_at,
        published_at=document.published_at,
    )
