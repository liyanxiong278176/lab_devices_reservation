from __future__ import annotations

import asyncio
import hashlib
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Header, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select, update
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
from app.ai.providers import test_provider
from app.ai.rag.qdrant_store import QdrantKnowledgeStore, split_text
from app.ai.runtime import append_run_event, run_event_stream
from app.ai.schemas import (
    AiConfigData,
    AiConfigTestData,
    AiEmbeddingRebuildData,
    AiEmbeddingRebuildRequest,
    ChatRequest,
    ConversationCreateRequest,
    ConversationData,
    KnowledgeCreateRequest,
    KnowledgeData,
    KnowledgeReviewRequest,
)
from app.ai.usage import (
    add_aux_usage,
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
from app.infrastructure.cache.redis import reservation_lock
from app.infrastructure.db.models import (
    AiAuxUsageEvent,
    AiCheckpoint,
    AiCheckpointWrite,
    AiConfirmation,
    AiConversation,
    AiEmbeddingRebuildJob,
    AiKnowledgeIndexState,
    AiMessage,
    AiRun,
    AiRunEvent,
    AiUsageBucket,
    AiUsageEvent,
    College,
    KnowledgeChunk,
    KnowledgeDocument,
    OutboxTask,
    UploadAsset,
)
from app.infrastructure.db.session import get_db

router = APIRouter()


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
            "聊天模型尚未配置，请联系系统管理员检查后端 .env 并重启服务",
            503,
        )
    if embedding is None or not embedding.enabled or not embedding.api_key:
        raise ApiError(
            "AI_RAG_NOT_CONFIGURED",
            "知识检索模型尚未配置，请联系系统管理员检查后端 .env 中的 Embedding Key",
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
            metadata_json={"run_key": run.run_key},
        )
    )
    await session.flush()
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
    result: dict[str, Any] = {
        "mine": await user_usage(session, principal.user_id, settings)
    }
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
        raise ApiError("AI_EMBEDDING_NOT_CONFIGURED", "请先在后端 .env 配置 Embedding Key", 409)
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
    document = KnowledgeDocument(
        college_id=college_id,
        title=payload.title.strip(),
        source_type=payload.source_type,
        body=payload.body.strip(),
        extracted_text=payload.body.strip(),
        parse_status="PARSED",
        version=1,
        status="DRAFT",
        created_by=principal.user_id,
        checksum=hashlib.sha256(payload.body.encode()).hexdigest(),
    )
    session.add(document)
    await session.commit()
    await session.refresh(document)
    return ApiResponse.ok(_knowledge_data(document, 0))


@router.post("/ai/knowledge/upload", response_model=ApiResponse[KnowledgeData], status_code=201)
async def upload_knowledge_document(
    request: Request,
    title: str = Form(min_length=1, max_length=200),
    source_type: str = Form(default="SOP", max_length=40),
    college_id: int | None = Form(default=None, gt=0),
    file: UploadFile = File(...),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[KnowledgeData]:
    if college_id is None and not principal.is_system_admin:
        college_id = college_scope(principal)
    if not _can_manage_knowledge(principal, college_id):
        raise ApiError("FORBIDDEN", "只能维护全局或自己学院的知识库", 403)
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
            await session.commit()
            await session.refresh(document)
        except Exception:
            await session.rollback()
            await asyncio.to_thread(target.unlink, missing_ok=True)
            raise
    return ApiResponse.ok(_knowledge_data(document, 0))


@router.get("/ai/knowledge/{document_id}")
async def get_knowledge_document(
    document_id: int,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    document = await _load_knowledge_document(session, principal, document_id)
    if not _can_manage_knowledge(principal, document.college_id):
        raise ApiError("DOCUMENT_NOT_FOUND", "知识文档不存在或无权操作", 404)
    return ApiResponse.ok(
        {
            **_knowledge_data(document, 0).model_dump(),
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


@router.post("/ai/knowledge/{document_id}/parse", response_model=ApiResponse[KnowledgeData])
async def parse_knowledge_document(
    document_id: int,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[KnowledgeData]:
    document = await _load_knowledge_document(session, principal, document_id)
    if not document.source_file_path or document.parse_status not in {"UPLOADED", "FAILED"}:
        raise ApiError("DOCUMENT_PARSE_STATE_INVALID", "文档当前状态不允许启动解析", 409)
    ocr_runtime = await get_component_config(session, request.app.state.settings, "mineru")
    if ocr_runtime is None or not ocr_runtime.enabled or not ocr_runtime.api_key:
        raise ApiError("MINERU_NOT_CONFIGURED", "MinerU 尚未配置或未启用，请先完成服务配置", 503)
    document.parse_status = "QUEUED"
    document.parse_error = None
    task_key = f"ai-knowledge-parse:{document.id}:v{document.version}:{uuid4().hex}"
    session.add(
        OutboxTask(
            task_key=task_key,
            task_type="AI_KNOWLEDGE_PARSE",
            aggregate_key=f"ai-knowledge:{document.id}",
            college_id=document.college_id,
            payload={"document_id": document.id, "task_key": task_key},
            status="PENDING",
            execute_at=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    await session.commit()
    await session.refresh(document)
    return ApiResponse.ok(_knowledge_data(document, 0))


@router.put("/ai/knowledge/{document_id}/review", response_model=ApiResponse[KnowledgeData])
async def review_knowledge_document(
    document_id: int,
    payload: KnowledgeReviewRequest,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[KnowledgeData]:
    document = await _load_knowledge_document(session, principal, document_id)
    if document.parse_status not in {"PARSED", "REVIEWED", "PUBLISHED"}:
        raise ApiError("DOCUMENT_NOT_PARSED", "请等待文档解析完成后再审核", 409)
    if document.status == "PUBLISHED":
        document.version += 1
    document.reviewed_text = payload.reviewed_text.strip()
    document.reviewed_by = principal.user_id
    document.reviewed_at = datetime.now(UTC).replace(tzinfo=None)
    document.parse_status = "REVIEWED"
    document.status = "DRAFT"
    await session.commit()
    await session.refresh(document)
    return ApiResponse.ok(_knowledge_data(document, 0))


@router.get("/ai/knowledge/{document_id}/chunks/preview")
async def preview_knowledge_chunks(
    document_id: int,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[list[dict[str, Any]]]:
    document = await _load_knowledge_document(session, principal, document_id)
    content = document.reviewed_text or document.extracted_text or document.body
    chunks = split_text(content)
    return ApiResponse.ok(
        [
            {"index": index, "content": chunk, "characters": len(chunk)}
            for index, chunk in enumerate(chunks)
        ]
    )


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
    if document.parse_status != "REVIEWED" or not document.reviewed_text:
        raise ApiError("DOCUMENT_REVIEW_REQUIRED", "请先审核并确认提取内容，再发布到知识库", 409)
    runtime = await get_component_config(session, request.app.state.settings, "embedding")
    if runtime is None or not runtime.enabled or not runtime.api_key:
        raise ApiError("AI_EMBEDDING_NOT_CONFIGURED", "Embedding 服务尚未配置或未启用", 503)
    store = QdrantKnowledgeStore(request.app.state.settings, runtime)
    try:
        chunks = split_text(document.reviewed_text)
        point_ids = await store.upsert_chunks(
            document_id=document.id,
            title=document.title,
            source_type=document.source_type,
            college_id=document.college_id,
            chunks=chunks,
            version=document.version,
        )
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
                    metadata_json={
                        "title": document.title,
                        "source_type": document.source_type,
                        "version": document.version,
                    },
                )
            )
        document.body = document.reviewed_text
        document.status = "PUBLISHED"
        document.parse_status = "PUBLISHED"
        document.published_at = datetime.now(UTC).replace(tzinfo=None)
        add_aux_usage(
            session,
            event_key=f"embedding-publish:{document.id}:v{document.version}",
            component="embedding",
            operation="document_index",
            model=runtime.model,
            user_id=principal.user_id,
            college_id=document.college_id,
            item_count=len(chunks),
            input_units=sum(len(chunk) for chunk in chunks),
        )
        await session.commit()
        try:
            await store.delete_old_document_versions(document.id, document.version)
        except Exception:
            # MySQL's current chunk rows are the authorization source; stale Qdrant
            # points are ignored and can be removed by a later index maintenance.
            pass
        return ApiResponse.ok(_knowledge_data(document, len(chunks)))
    finally:
        await store.close()


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
    counts = (
        {
            int(row[0]): int(row[1])
            for row in (
                await session.execute(
                    select(KnowledgeChunk.document_id, func.count(KnowledgeChunk.id))
                    .where(KnowledgeChunk.document_id.in_(document_ids))
                    .group_by(KnowledgeChunk.document_id)
                )
            ).all()
        }
        if document_ids
        else {}
    )
    return ApiResponse.ok([_knowledge_data(row, counts.get(row.id, 0)) for row in rows])


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
    document.body = ""
    document.extracted_text = None
    document.reviewed_text = None
    document.source_file_path = None
    document.status = "DELETED"
    document.parse_status = "DELETED"
    document.parse_error = None
    await session.commit()
    return ApiResponse.ok({"document_id": document.id, "deleted": True})


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
        source_file_name=document.source_file_name,
        parse_status=document.parse_status,
        parse_error=document.parse_error,
    )
