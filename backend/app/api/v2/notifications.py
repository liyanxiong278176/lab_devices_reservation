from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import date, datetime
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import get_authorization_snapshot
from app.auth.security import (
    Principal,
    college_scope,
    get_current_principal,
    require_permissions,
    resolve_principal,
)
from app.auth.sessions import get_session
from app.common.response import ApiResponse
from app.core.client_ip import resolve_client_ip
from app.core.errors import ApiError
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.db.models import Notification, User
from app.infrastructure.db.pagination import delayed_page_ids, page_metadata, page_offset
from app.infrastructure.db.session import get_db
from app.infrastructure.notifications.realtime import NotificationHub, NotificationStream

logger = logging.getLogger(__name__)

router = APIRouter(
    dependencies=[
        Depends(enforce_authenticated_rate_limit),
        Depends(require_permissions("notification:read:own")),
    ]
)
stream_router = APIRouter()


def _row(row: Notification) -> dict[str, object]:
    return {
        "id": row.id,
        "userId": row.user_id,
        "type": row.type,
        "title": row.title,
        "content": row.content,
        "relatedId": row.related_id,
        "relatedType": row.related_type,
        "isRead": 1 if row.is_read else 0,
        "createdAt": row.created_at,
    }


def _conditions(principal: Principal, only_unread: bool = False):
    values = [Notification.user_id == principal.user_id]
    scope = college_scope(principal)
    if scope is not None:
        values.append(Notification.college_id == scope)
    if only_unread:
        values.append(Notification.is_read.is_(False))
    return values


def _sse(event: str, data: dict[str, object], *, event_id: int | None = None) -> str:
    fields = []
    if event_id is not None:
        fields.append(f"id: {event_id}")
    fields.append(f"event: {event}")
    encoded_data = json.dumps(
        data,
        ensure_ascii=False,
        separators=(",", ":"),
        default=_sse_json_default,
    )
    fields.append(f"data: {encoded_data}")
    return "\n".join(fields) + "\n\n"


def _sse_json_default(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Unsupported SSE value: {type(value).__name__}")


def _last_event_cursor(value: str | None) -> int | None:
    if value is None:
        return None
    if len(value) > 19 or not value.isascii() or not value.isdecimal():
        raise ApiError("INVALID_EVENT_CURSOR", "通知游标无效", 400)
    cursor = int(value)
    if cursor > 9_223_372_036_854_775_807:
        raise ApiError("INVALID_EVENT_CURSOR", "通知游标无效", 400)
    return cursor


def _assert_stream_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        return
    settings = request.app.state.settings
    configured = {str(value).rstrip("/").lower() for value in settings.cors_origins}
    normalized = origin.rstrip("/").lower()
    host = request.headers.get("host", "").lower()
    origin_parts = urlsplit(origin)
    same_host = origin_parts.scheme in {"http", "https"} and origin_parts.netloc.lower() == host
    if normalized not in configured and not same_host:
        raise ApiError("ORIGIN_NOT_ALLOWED", "请求来源不受信任", 403)


async def resolve_notification_stream_principal(request: Request) -> Principal:
    """Authenticate without retaining a request-scoped DB session for the stream."""
    settings = request.app.state.settings
    token = request.cookies.get(settings.access_cookie_name)
    if not token:
        raise ApiError("AUTH_REQUIRED", "请先登录", 401)
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        raise ApiError("SERVICE_BUSY", "通知服务暂不可用", 503)
    try:
        async with asyncio.timeout(settings.notification_sse_auth_timeout_seconds):
            async with factory() as session:
                principal = await resolve_principal(request, token, session)
    except TimeoutError as exc:
        raise ApiError("AUTH_TIMEOUT", "登录验证超时", 503) from exc
    if not principal.has_permission("notification:read:own"):
        raise ApiError("FORBIDDEN", "当前账号没有查看通知的权限", 403)
    return principal


async def _stream_still_authorized(request: Request, principal: Principal) -> bool:
    """Recheck revocation and tenant/permission changes on long-lived streams."""
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        return False
    session_record = await get_session(request, principal.session_id)
    if session_record is None:
        return False
    try:
        session_user_id = int(session_record["user_id"])
        expires_at = int(session_record["expires_at"])
    except (KeyError, TypeError, ValueError):
        return False
    if session_user_id != principal.user_id or expires_at <= int(time.time()):
        return False
    async with factory() as session:
        user = await session.scalar(
            select(User).where(User.id == principal.user_id, User.status == 1)
        )
        if user is None or user.college_id != principal.college_id:
            return False
        snapshot = await get_authorization_snapshot(
            request,
            session,
            user_id=user.id,
            session_id=principal.session_id,
            session_expires_at=expires_at,
        )
    return "SYS_ADMIN" in snapshot.roles or "notification:read:own" in snapshot.permissions


async def _notification_batch(
    request: Request,
    principal: Principal,
    cursor: int,
    *,
    limit: int,
) -> tuple[list[dict[str, object]], int, int, bool]:
    """Read the newest bounded replay page in delivery order and its high-water cursor."""
    factory = request.app.state.session_factory
    conditions = [*_conditions(principal), Notification.delivery_sequence > cursor]
    async with factory() as session:
        newest_first = list(
            (
                await session.scalars(
                    select(Notification)
                    .where(*conditions)
                    .order_by(Notification.delivery_sequence.desc())
                    .limit(limit + 1)
                )
            ).all()
        )
        if len(newest_first) <= limit:
            rows = list(reversed(newest_first))
            events = [{**_row(row), "deliverySequence": row.delivery_sequence} for row in rows]
            return events, len(events), events[-1]["deliverySequence"] if events else cursor, False

        total = int(
            await session.scalar(select(func.count(Notification.id)).where(*conditions)) or 0
        )
        high_water = int(
            await session.scalar(
                select(func.max(Notification.delivery_sequence)).where(*_conditions(principal))
            )
            or cursor
        )
        # Pick the newest bounded slice, then reverse it so clients still see a
        # strict ascending sequence. Older pending rows remain available through
        # the HTTP history endpoint before the SSE cursor advances to high-water.
        events = [
            {**_row(row), "deliverySequence": row.delivery_sequence}
            for row in reversed(newest_first[:limit])
        ]
        return events, total, high_water, True


async def _visible_sequence_head(request: Request, principal: Principal) -> int:
    async with request.app.state.session_factory() as session:
        return int(
            await session.scalar(
                select(func.max(Notification.delivery_sequence)).where(*_conditions(principal))
            )
            or 0
        )


async def _stream_events(
    request: Request,
    principal: Principal,
    stream: NotificationStream,
    last_event_cursor: int | None,
):
    settings = request.app.state.settings
    hub: NotificationHub = request.app.state.notification_hub
    max_replay = settings.notification_sse_max_replay_events

    if last_event_cursor is None:
        # A page reload/new login starts from the current head. HTTP history is
        # authoritative then; only EventSource's automatic reconnect replays.
        cursor = await _visible_sequence_head(request, principal)
    else:
        # A stale cursor from a prior tenant scope or a forged huge value must
        # not skip all future rows for this authenticated user.
        cursor = min(last_event_cursor, await _visible_sequence_head(request, principal))

    yield ": connected\n\n"
    # Establish the user's cursor immediately, even when no notification has
    # arrived yet, so the first automatic reconnect can recover offline rows.
    yield _sse(
        "stream-ready",
        {"replay": last_event_cursor is not None},
        event_id=cursor,
    )
    if last_event_cursor is not None:
        yield _sse("batch-start", {"replay": True})
        events, pending_count, high_water, overflow = await _notification_batch(
            request, principal, cursor, limit=max_replay
        )
        for event in events:
            sequence = int(event["deliverySequence"])
            yield _sse("notification", event, event_id=sequence)
            cursor = sequence
        if overflow:
            # The HTTP history endpoint carries the portion above the replay cap.
            # Advancing to this user's visible high-water mark prevents SSE from
            # turning a long offline period into an unbounded replay loop.
            cursor = high_water
        yield _sse(
            "batch-complete",
            {
                "replay": True,
                "deliveredCount": len(events),
                "omittedCount": max(0, pending_count - len(events)) if overflow else 0,
                "historySyncRequired": overflow,
            },
            event_id=cursor if overflow else None,
        )

    next_revalidation = time.monotonic() + settings.notification_sse_revalidate_seconds
    while not stream.closed.is_set():
        woke = await hub.wait(stream, settings.notification_sse_heartbeat_seconds)
        if stream.closed.is_set():
            yield _sse("auth-revoked", {"reconnect": False})
            return

        notification_pending, read_state_pending = await hub.take_pending(stream)
        if read_state_pending:
            yield _sse("read-state-changed", {"scope": "current-user"})

        now = time.monotonic()
        if now >= next_revalidation:
            try:
                still_authorized = await _stream_still_authorized(request, principal)
            except Exception:
                logger.exception("notification stream authorization recheck failed")
                still_authorized = False
            if not still_authorized:
                yield _sse("auth-revoked", {"reconnect": False})
                return
            next_revalidation = now + settings.notification_sse_revalidate_seconds

        # Query on every heartbeat as well as every relay wake-up. That repairs
        # missed Pub/Sub hints without retaining a database connection.
        events, pending_count, high_water, overflow = await _notification_batch(
            request, principal, cursor, limit=max_replay
        )
        if events:
            yield _sse("batch-start", {"replay": False})
            for event in events:
                sequence = int(event["deliverySequence"])
                yield _sse("notification", event, event_id=sequence)
                cursor = sequence
            if overflow:
                cursor = high_water
            yield _sse(
                "batch-complete",
                {
                    "replay": False,
                    "deliveredCount": len(events),
                    "omittedCount": max(0, pending_count - len(events)) if overflow else 0,
                    "historySyncRequired": overflow,
                },
                event_id=cursor if overflow else None,
            )
        elif not woke or not notification_pending:
            yield ": heartbeat\n\n"


@stream_router.get("/notifications/stream")
async def notification_stream(request: Request) -> StreamingResponse:
    _assert_stream_origin(request)
    settings = request.app.state.settings
    hub: NotificationHub = request.app.state.notification_hub
    peer = request.client.host if request.client else None
    client_ip = resolve_client_ip(
        peer,
        request.headers.get("x-forwarded-for"),
        settings.trusted_proxy_ips,
    )
    stream = await hub.reserve_pending(
        client_ip,
        max_pending=settings.notification_sse_max_pending,
        max_per_ip=settings.notification_sse_max_pending_per_ip,
    )
    if stream is None:
        raise ApiError("STREAM_CAPACITY", "实时通知连接数已满，请稍后重试", 503)

    try:
        async with asyncio.timeout(settings.notification_sse_auth_timeout_seconds):
            principal = await resolve_notification_stream_principal(request)
        await enforce_authenticated_rate_limit(request, principal)
        connected = await hub.connect(
            principal.user_id,
            stream,
            max_total=settings.notification_sse_max_connections,
            max_per_user=settings.notification_sse_max_per_user,
            session_id=principal.session_id,
        )
        if not connected:
            raise ApiError("STREAM_CAPACITY", "实时通知连接数已满，请稍后重试", 503)
        cursor = _last_event_cursor(request.headers.get("last-event-id"))
    except TimeoutError as exc:
        await hub.disconnect_pending(stream)
        raise ApiError("AUTH_TIMEOUT", "登录验证超时", 503) from exc
    except BaseException:
        await hub.disconnect_pending(stream)
        raise

    async def body():
        try:
            async for chunk in _stream_events(request, principal, stream, cursor):
                yield chunk
        finally:
            await hub.disconnect(principal.user_id, stream)

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/notifications/mine", response_model=ApiResponse[dict[str, object]])
async def my_notifications(
    only_unread: bool = Query(default=False, alias="onlyUnread"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=10, ge=1, le=100),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, object]]:
    page_offset(page, size)
    conditions = _conditions(principal, only_unread)
    total = int(await session.scalar(select(func.count(Notification.id)).where(*conditions)) or 0)
    page_ids = delayed_page_ids(
        select(Notification.id).where(*conditions),
        Notification.id,
        page=page,
        page_size=size,
    )
    rows = list(
        (
            await session.scalars(
                select(Notification)
                .join(page_ids, page_ids.c.id == Notification.id)
                .order_by(Notification.id.desc())
            )
        ).all()
    )
    pages, truncated = page_metadata(total, size)
    return ApiResponse.ok(
        {
            "records": [_row(row) for row in rows],
            "total": total,
            "size": size,
            "current": page,
            "pages": pages,
            "truncated": truncated,
        }
    )


@router.patch("/notifications/{notification_id}/read", response_model=ApiResponse[None])
async def mark_read(
    request: Request,
    notification_id: int,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    result = await session.execute(
        update(Notification)
        .where(
            *_conditions(principal),
            Notification.id == notification_id,
            Notification.is_read.is_(False),
        )
        .values(is_read=True)
    )
    changed = result.rowcount == 1
    if not changed:
        exists = await session.scalar(
            select(Notification.id).where(
                *_conditions(principal), Notification.id == notification_id
            )
        )
        if exists is None:
            raise ApiError("NOTIFICATION_NOT_FOUND", "通知不存在或无权操作", 404)
    await session.commit()
    if changed:
        await _publish_read_state_hint(
            request,
            principal.user_id,
            {"eventType": "read_state_changed", "notificationId": notification_id},
        )
    return ApiResponse.ok(None)


@router.patch("/notifications/read-all", response_model=ApiResponse[None])
async def mark_all_read(
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    result = await session.execute(
        update(Notification).where(*_conditions(principal, only_unread=True)).values(is_read=True)
    )
    await session.commit()
    if result.rowcount and result.rowcount > 0:
        await _publish_read_state_hint(
            request,
            principal.user_id,
            {"eventType": "read_state_changed", "all": True},
        )
    return ApiResponse.ok(None)


async def _publish_read_state_hint(
    request: Request,
    user_id: int,
    payload: dict[str, object],
) -> None:
    """Notify every user's online SSE connection after the DB commit."""
    relay = getattr(request.app.state, "notification_relay", None)
    hub: NotificationHub | None = getattr(request.app.state, "notification_hub", None)
    try:
        if relay is not None:
            await relay.publish(user_id, payload)
        elif hub is not None:
            await hub.publish(user_id, payload)
    except Exception:
        # Read status is committed in MySQL. A lost Pub/Sub hint is repaired by
        # reconnect/history reads and must not turn a successful PATCH into 500.
        logger.warning("notification read-state fan-out failed", exc_info=True)
