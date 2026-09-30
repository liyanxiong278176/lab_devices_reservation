from __future__ import annotations

from datetime import UTC, date, datetime
from math import ceil
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.core.settings import Settings
from app.infrastructure.db.models import (
    AiAuxUsageEvent,
    AiRun,
    AiUsageBucket,
    AiUsageEvent,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


def usage_day() -> date:
    return datetime.now(UTC).astimezone(SHANGHAI).date()


def estimate_reservation(content: str, *, max_output_tokens: int, context_documents: int) -> int:
    # Chinese text commonly consumes close to one token per character. Reserve
    # conservatively for system/history/RAG context and up to three initial calls:
    # query rewrite, planner, and a natural-language answer.
    return max(1, ceil(len(content) * 1.5) + context_documents * 500 + 3 * max_output_tokens)


def estimate_additional_reservation(content: str, *, max_output_tokens: int) -> int:
    """Reserve one more planner request using the full prompt estimate."""
    return max(1, ceil(len(content) * 1.5) + max_output_tokens)


def _usage_scopes(user_id: int, college_id: int | None) -> list[tuple[str, int]]:
    scopes = [("global", 0)]
    if college_id is not None:
        scopes.append(("college", college_id))
    scopes.append(("user", user_id))
    return scopes


async def _ensure_bucket(
    session: AsyncSession,
    *,
    scope_type: str,
    scope_id: int,
    day: date,
) -> None:
    values = {
        "scope_type": scope_type,
        "scope_id": scope_id,
        "usage_date": day,
        "reserved_tokens": 0,
        "used_tokens": 0,
    }
    dialect = session.bind.dialect.name if session.bind is not None else ""
    if dialect == "mysql":
        statement = (
            mysql_insert(AiUsageBucket)
            .values(**values)
            .on_duplicate_key_update(scope_type=scope_type)
        )
    elif dialect == "sqlite":
        statement = (
            sqlite_insert(AiUsageBucket)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["scope_type", "scope_id", "usage_date"])
        )
    else:
        if (
            await session.scalar(
                select(AiUsageBucket.id).where(
                    AiUsageBucket.scope_type == scope_type,
                    AiUsageBucket.scope_id == scope_id,
                    AiUsageBucket.usage_date == day,
                )
            )
            is None
        ):
            session.add(AiUsageBucket(**values))
            await session.flush()
        return
    await session.execute(statement)


async def reserve_chat_tokens(
    session: AsyncSession,
    *,
    settings: Settings,
    run_id: int,
    user_id: int,
    college_id: int | None,
    token_reservation: int,
) -> None:
    limits = {
        "global": settings.ai_global_daily_token_cap,
        "college": settings.ai_college_daily_token_cap,
        "user": settings.ai_user_daily_token_cap,
    }
    caps = [(*scope, limits[scope[0]]) for scope in _usage_scopes(user_id, college_id)]
    if any(cap <= 0 for _scope, _scope_id, cap in caps):
        raise ApiError("AI_QUOTA_NOT_CONFIGURED", "AI 每日个人、学院和全校额度尚未完整配置", 503)

    day = usage_day()
    # Keep the same explicit lock order used by settle_chat_tokens.
    for scope_type, scope_id, _cap in caps:
        await _ensure_bucket(
            session,
            scope_type=scope_type,
            scope_id=scope_id,
            day=day,
        )
    rows: list[tuple[AiUsageBucket, int]] = []
    for scope_type, scope_id, cap in caps:
        row = await session.scalar(
            select(AiUsageBucket)
            .where(
                AiUsageBucket.scope_type == scope_type,
                AiUsageBucket.scope_id == scope_id,
                AiUsageBucket.usage_date == day,
            )
            .with_for_update()
        )
        if row is None:
            raise ApiError("AI_QUOTA_UNAVAILABLE", "AI 额度暂不可用，请重试", 503)
        if row.used_tokens + row.reserved_tokens + token_reservation > cap:
            scope_label = {"global": "全校", "college": "本学院", "user": "个人"}[scope_type]
            raise ApiError(
                "AI_DAILY_QUOTA_EXCEEDED",
                f"今日{scope_label} AI Token 额度不足",
                429,
            )
        rows.append((row, cap))
    for row, _cap in rows:
        row.reserved_tokens += token_reservation
    session.add(
        AiUsageEvent(
            run_id=run_id,
            user_id=user_id,
            college_id=college_id,
            usage_date=day,
            reserved_tokens=token_reservation,
            status="RESERVED",
        )
    )
    await session.flush()


async def reserve_additional_chat_tokens(
    session: AsyncSession,
    *,
    settings: Settings,
    run_id: int,
    reservation_key: str,
    token_reservation: int,
) -> bool:
    """Atomically reserve quota for an extra planner call, idempotent on resume."""
    run = await session.scalar(select(AiRun).where(AiRun.id == run_id).with_for_update())
    if run is None or run.status != "RUNNING":
        await session.rollback()
        raise ApiError("AI_RUN_STOPPED", "AI 任务已停止，不能继续调用模型", 409)

    state = dict(run.state_json or {})
    reservation_keys = list(state.get("_quota_reservation_keys", []))
    if reservation_key in reservation_keys:
        await session.commit()
        return False

    event = await session.scalar(
        select(AiUsageEvent).where(AiUsageEvent.run_id == run_id).with_for_update()
    )
    if event is None or event.status != "RESERVED":
        await session.rollback()
        raise ApiError("AI_QUOTA_UNAVAILABLE", "AI 额度预留记录不可用，已停止继续调用", 503)

    limits = {
        "global": settings.ai_global_daily_token_cap,
        "college": settings.ai_college_daily_token_cap,
        "user": settings.ai_user_daily_token_cap,
    }
    caps = [
        (*scope, limits[scope[0]])
        for scope in _usage_scopes(event.user_id, event.college_id)
    ]
    if any(cap <= 0 for _scope, _scope_id, cap in caps):
        await session.rollback()
        raise ApiError("AI_QUOTA_NOT_CONFIGURED", "AI 每日额度尚未完整配置", 503)

    for scope_type, scope_id, _cap in caps:
        await _ensure_bucket(
            session,
            scope_type=scope_type,
            scope_id=scope_id,
            day=event.usage_date,
        )
    rows: list[tuple[AiUsageBucket, int, str]] = []
    for scope_type, scope_id, cap in caps:
        row = await session.scalar(
            select(AiUsageBucket)
            .where(
                AiUsageBucket.scope_type == scope_type,
                AiUsageBucket.scope_id == scope_id,
                AiUsageBucket.usage_date == event.usage_date,
            )
            .with_for_update()
        )
        if row is None:
            await session.rollback()
            raise ApiError("AI_QUOTA_UNAVAILABLE", "AI 额度暂不可用，已停止继续调用", 503)
        if row.used_tokens + row.reserved_tokens + token_reservation > cap:
            scope_label = {"global": "全校", "college": "本学院", "user": "个人"}[scope_type]
            await session.rollback()
            raise ApiError(
                "AI_DAILY_QUOTA_EXCEEDED",
                f"今日{scope_label} AI Token 额度不足，已停止继续调用",
                429,
            )
        rows.append((row, cap, scope_type))

    for row, _cap, _scope_type in rows:
        row.reserved_tokens += token_reservation
    event.reserved_tokens += token_reservation
    reservation_keys.append(reservation_key)
    state["_quota_reservation_keys"] = reservation_keys
    run.state_json = state
    # The reservation and idempotency marker must be durable before the model call.
    await session.commit()
    return True


async def settle_chat_tokens(
    session: AsyncSession,
    *,
    run_id: int,
    input_tokens: int,
    output_tokens: int,
    failed: bool = False,
) -> None:
    event = await session.scalar(
        select(AiUsageEvent).where(AiUsageEvent.run_id == run_id).with_for_update()
    )
    if event is None or event.status != "RESERVED":
        return
    # A provider request can be billable even if a later graph node fails.
    actual = max(0, input_tokens) + max(0, output_tokens)
    scopes = _usage_scopes(event.user_id, event.college_id)
    for scope_type, scope_id in scopes:
        row = await session.scalar(
            select(AiUsageBucket)
            .where(
                AiUsageBucket.scope_type == scope_type,
                AiUsageBucket.scope_id == scope_id,
                AiUsageBucket.usage_date == event.usage_date,
            )
            .with_for_update()
        )
        if row is None:
            raise ApiError("AI_QUOTA_UNAVAILABLE", "AI 额度账本不完整", 500)
        row.reserved_tokens = max(0, row.reserved_tokens - event.reserved_tokens)
        row.used_tokens += actual
    event.input_tokens = max(0, input_tokens)
    event.output_tokens = max(0, output_tokens)
    event.status = "FAILED" if failed else "SETTLED"
    event.settled_at = datetime.now(UTC).replace(tzinfo=None)


async def user_usage(
    session: AsyncSession,
    user_id: int,
    settings: Settings,
) -> dict[str, int | str]:
    day = usage_day()
    values = await session.execute(
        select(
            func.coalesce(AiUsageBucket.used_tokens, 0),
            func.coalesce(AiUsageBucket.reserved_tokens, 0),
        ).where(
            AiUsageBucket.scope_type == "user",
            AiUsageBucket.scope_id == user_id,
            AiUsageBucket.usage_date == day,
        )
    )
    used, reserved = values.one_or_none() or (0, 0)
    return {
        "date": day.isoformat(),
        "used_tokens": int(used),
        "reserved_tokens": int(reserved),
        "daily_cap": settings.ai_user_daily_token_cap,
    }


async def scoped_usage(
    session: AsyncSession,
    *,
    scope_type: str,
    scope_id: int | None,
) -> dict[str, int | str | None]:
    day = usage_day()
    query = select(
        func.coalesce(func.sum(AiUsageBucket.used_tokens), 0),
        func.coalesce(func.sum(AiUsageBucket.reserved_tokens), 0),
    ).where(
        AiUsageBucket.usage_date == day,
        AiUsageBucket.scope_type == scope_type,
    )
    if scope_id is not None:
        query = query.where(AiUsageBucket.scope_id == scope_id)
    used, reserved = (await session.execute(query)).one()
    return {
        "date": day.isoformat(),
        "scope": scope_type,
        "college_id": scope_id,
        "used_tokens": int(used),
        "reserved_tokens": int(reserved),
    }


def add_aux_usage(
    session: AsyncSession,
    *,
    event_key: str,
    component: str,
    operation: str,
    model: str,
    user_id: int,
    college_id: int | None,
    item_count: int,
    input_units: int,
) -> None:
    session.add(
        AiAuxUsageEvent(
            event_key=event_key,
            component=component,
            operation=operation,
            model=model,
            user_id=user_id,
            college_id=college_id,
            usage_date=usage_day(),
            request_count=1,
            item_count=max(0, item_count),
            input_units=max(0, input_units),
            status="SUCCEEDED",
        )
    )
