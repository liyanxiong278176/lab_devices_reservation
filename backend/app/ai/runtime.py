from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload

from app.ai.config import get_component_config, get_runtime_config
from app.ai.graph.harness import AgentHarness
from app.ai.usage import settle_chat_tokens
from app.auth.security import Principal
from app.infrastructure.db.models import (
    AiConversation,
    AiRun,
    AiRunEvent,
    Role,
    User,
)
from app.infrastructure.db.session import build_session_factory

logger = logging.getLogger(__name__)
TERMINAL_RUN_STATUSES = {"COMPLETED", "WAITING_CONFIRMATION", "FAILED", "CANCELLED"}


async def append_run_event(
    session_factory: Any,
    run_id: int,
    payload: dict[str, Any],
) -> int:
    async with session_factory() as session, session.begin():
        await session.scalar(select(AiRun.id).where(AiRun.id == run_id).with_for_update())
        sequence = (
            int(
                await session.scalar(
                    select(func.coalesce(func.max(AiRunEvent.sequence), 0)).where(
                        AiRunEvent.run_id == run_id
                    )
                )
                or 0
            )
            + 1
        )
        row = AiRunEvent(
            run_id=run_id,
            sequence=sequence,
            event_type=str(payload.get("type", "message"))[:40],
            payload=payload,
        )
        session.add(row)
        await session.flush()
        return int(row.id)


async def execute_ai_run(app: FastAPI, run_id: int) -> None:
    active = getattr(app.state, "ai_run_tasks", None)
    if active is None:
        active = app.state.ai_run_tasks = {}
    current_task = asyncio.current_task()
    if current_task is not None:
        active[run_id] = current_task
    started = time.perf_counter()
    outcome = "returned"
    try:
        await _execute_ai_run(app, run_id)
    except asyncio.CancelledError:
        outcome = "cancelled"
        raise
    except Exception:
        outcome = "error"
        raise
    finally:
        metrics = getattr(app.state, "metrics", None)
        if metrics is not None:
            metrics.observe(
                "ai_run_duration_seconds",
                time.perf_counter() - started,
                labels={"outcome": outcome},
            )
        logger.info(
            "AI run finished run_id=%s duration_ms=%s outcome=%s",
            run_id,
            int((time.perf_counter() - started) * 1000),
            outcome,
        )
        active.pop(run_id, None)


async def _execute_ai_run(app: FastAPI, run_id: int) -> None:
    factory = getattr(app.state, "session_factory", None)
    if factory is None:
        from app.infrastructure.db.session import build_engine

        engine = build_engine(app.state.settings)
        app.state.db_engine = engine
        factory = build_session_factory(engine)
        app.state.session_factory = factory
    async with factory() as session:
        run = await session.scalar(select(AiRun).where(AiRun.id == run_id).with_for_update())
        if run is None or run.status in TERMINAL_RUN_STATUSES:
            return
        if run.status not in {"QUEUED", "RUNNING"}:
            return
        run.status = "RUNNING"
        await session.commit()
        conversation = await session.scalar(
            select(AiConversation).where(AiConversation.id == run.conversation_id)
        )
        user = await session.scalar(
            select(User)
            .options(selectinload(User.roles).selectinload(Role.permissions))
            .where(User.id == run.user_id, User.status == 1)
        )
        if conversation is None or user is None or user.college_id != run.college_id:
            await _fail_run(session, run_id, "AI_CONTEXT_CHANGED")
            await append_run_event(
                factory,
                run_id,
                {
                    "type": "error",
                    "code": "AI_CONTEXT_CHANGED",
                    "message": "账号或学院权限已变化，请重新发起对话",
                },
            )
            await _settle_failed(session, run_id)
            return
        current_permissions = {
            permission.permission_code for role in user.roles for permission in role.permissions
        }
        if "ai:use" not in current_permissions:
            await _fail_run(session, run_id, "AI_PERMISSION_REVOKED")
            await append_run_event(
                factory,
                run_id,
                {
                    "type": "error",
                    "code": "AI_PERMISSION_REVOKED",
                    "message": "当前账号已无权使用 AI 工作台，请联系管理员",
                },
            )
            await _settle_failed(session, run_id)
            return
        principal = Principal(
            user_id=user.id,
            username=user.username,
            college_id=user.college_id,
            roles=tuple(role.role_code for role in user.roles),
            token_type="access",
            token_id=f"ai-run-{run_id}",
            permissions=tuple(sorted(current_permissions)),
        )
        runtime = await get_runtime_config(session, principal, app.state.settings)
        embedding = await get_component_config(session, app.state.settings, "embedding")
        if (
            runtime is None
            or not runtime.enabled
            or not runtime.api_key
            or embedding is None
            or not embedding.enabled
            or not embedding.api_key
        ):
            await _fail_run(session, run_id, "AI_NOT_CONFIGURED")
            await append_run_event(
                factory,
                run_id,
                {
                    "type": "error",
                    "code": "AI_NOT_CONFIGURED",
                    "message": "AI 聊天或知识检索模型未配置，请联系系统管理员",
                },
            )
            await _settle_failed(session, run_id)
            return

        harness = AgentHarness(
            session,
            principal,
            app.state.settings,
            runtime,
            run,
            f"{conversation.graph_thread_id}:{run.id}",
            session_factory=factory,
            embedding_runtime=embedding,
        )
        await append_run_event(factory, run_id, {"type": "run_started", "run_id": run_id})
        token_buffer = ""
        try:
            async for event in harness.stream():
                event_type = str(event.get("type", "message"))
                if event_type == "token":
                    token_buffer += str(event.get("text", ""))
                    if len(token_buffer) < 80:
                        continue
                    event = {"type": "token", "text": token_buffer}
                    token_buffer = ""
                await append_run_event(factory, run_id, event)
            if token_buffer:
                await append_run_event(factory, run_id, {"type": "token", "text": token_buffer})
        except asyncio.CancelledError:
            await session.rollback()
            await _fail_run(session, run_id, "AI_RUN_CANCELLED", status="CANCELLED")
            await _settle_failed(session, run_id)
            await append_run_event(
                factory,
                run_id,
                {"type": "done", "status": "CANCELLED", "message": "任务已停止"},
            )
            return
        except Exception as exc:
            logger.error("AI run failed; run_id=%s error_type=%s", run_id, type(exc).__name__)
            await session.rollback()
            await _fail_run(session, run_id, "AI_RUN_FAILED")
            await _settle_failed(session, run_id)
            await append_run_event(
                factory,
                run_id,
                {
                    "type": "error",
                    "code": "AI_RUN_FAILED",
                    "message": "AI 服务暂时不可用，请稍后重试",
                },
            )
            return

        await session.refresh(run)
        failed = run.status == "FAILED"
        await settle_chat_tokens(
            session,
            run_id=run_id,
            input_tokens=harness.usage.input_tokens,
            output_tokens=harness.usage.output_tokens,
            failed=failed,
        )
        await session.commit()


async def _fail_run(
    session: Any,
    run_id: int,
    error_code: str,
    *,
    status: str = "FAILED",
) -> None:
    await session.execute(
        update(AiRun)
        .where(AiRun.id == run_id, AiRun.status.in_({"QUEUED", "RUNNING"}))
        .values(
            status=status,
            error_code=error_code,
            completed_at=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    await session.commit()


async def _settle_failed(session: Any, run_id: int) -> None:
    await settle_chat_tokens(
        session,
        run_id=run_id,
        input_tokens=0,
        output_tokens=0,
        failed=True,
    )
    await session.commit()


async def run_event_stream(
    app: FastAPI,
    *,
    run_id: int,
    user_id: int,
    after_event_id: int = 0,
):
    factory = getattr(app.state, "session_factory", None)
    if factory is None:
        from app.infrastructure.db.session import build_engine

        engine = build_engine(app.state.settings)
        app.state.db_engine = engine
        factory = build_session_factory(engine)
        app.state.session_factory = factory
    cursor = max(0, after_event_id)
    heartbeat_at = asyncio.get_running_loop().time()
    while True:
        async with factory() as session:
            run = await session.scalar(
                select(AiRun).where(AiRun.id == run_id, AiRun.user_id == user_id)
            )
            if run is None:
                return
            events = list(
                (
                    await session.scalars(
                        select(AiRunEvent)
                        .where(AiRunEvent.run_id == run_id, AiRunEvent.id > cursor)
                        .order_by(AiRunEvent.id)
                        .limit(100)
                    )
                ).all()
            )
            status = run.status
        for item in events:
            cursor = item.id
            body = json.dumps(item.payload, ensure_ascii=False, default=str)
            yield f"id: {item.id}\nevent: {item.event_type}\ndata: {body}\n\n"
            if item.event_type in {"done", "error"}:
                return
        if status in TERMINAL_RUN_STATUSES and not events:
            terminal = await _terminal_event(factory, run_id)
            if terminal is not None:
                event_id, payload = terminal
                body = json.dumps(payload, ensure_ascii=False, default=str)
                yield f"id: {event_id}\nevent: done\ndata: {body}\n\n"
            return
        now = asyncio.get_running_loop().time()
        if now - heartbeat_at >= app.state.settings.ai_run_event_heartbeat_seconds:
            yield ": keep-alive\n\n"
            heartbeat_at = now
        await asyncio.sleep(app.state.settings.ai_run_event_poll_seconds)


async def _terminal_event(session_factory: Any, run_id: int) -> tuple[int, dict[str, Any]] | None:
    async with session_factory() as session:
        run = await session.scalar(select(AiRun).where(AiRun.id == run_id))
        if run is None:
            return None
        return 0, {
            "type": "done",
            "status": run.status,
            "message": "任务已结束" if run.status != "FAILED" else "AI 任务失败，请稍后重试",
            "citations": run.citations_json or [],
            "text": run.output_text or "",
        }
