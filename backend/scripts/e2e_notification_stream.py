"""Isolated Redis Streams helpers for notification browser E2E scenarios.

Every database operation is scoped to an ``e2e-`` tenant. Redis writes are
refused unless the API is explicitly configured to use local Redis DB 14, which
the test runner verifies is empty before starting the API processes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from redis.asyncio import from_url
from sqlalchemy import select
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.settings import Settings
from app.infrastructure.db.models import Notification, OutboxTask, User
from app.infrastructure.db.session import build_engine, build_session_factory
from app.infrastructure.notifications.relay import RedisNotificationRelay
from app.infrastructure.notifications.sequence import next_delivery_sequence
from scripts.e2e_fixture import validate_prefix

BACKLOG_HOLD_KEY_PREFIX = "e2e:notification:"


def isolated_settings() -> Settings:
    settings = Settings()
    redis_url = make_url(settings.redis_url)
    if (
        settings.environment not in {"local", "test"}
        or redis_url.drivername != "redis"
        or redis_url.host != "127.0.0.1"
        or redis_url.port != 6379
        or redis_url.database != "14"
    ):
        raise RuntimeError(
            "E2E Redis writes require LAB_ENVIRONMENT=local|test and "
            "LAB_REDIS_URL=redis://127.0.0.1:6379/14"
        )
    return settings


def _event(notification: Notification) -> dict[str, object]:
    created_at = notification.created_at or datetime.now(UTC).replace(tzinfo=None)
    return {
        "eventType": "notification",
        "id": notification.id,
        "userId": notification.user_id,
        "deliverySequence": notification.delivery_sequence,
        "type": notification.type,
        "title": notification.title,
        "content": notification.content,
        "relatedId": notification.related_id,
        "relatedType": notification.related_type,
        "isRead": int(notification.is_read),
        "createdAt": created_at.isoformat(),
    }


async def _student(session_factory, prefix: str) -> User:
    student = await session_factory().scalar(select(User).where(User.username == f"{prefix}-user"))
    if student is None:
        raise RuntimeError("E2E student fixture does not exist")
    return student


async def enqueue_notification(prefix: str, title: str) -> dict[str, object]:
    settings = Settings()
    engine = build_engine(settings)
    factory = build_session_factory(engine)
    task_key = f"e2e:{prefix}:notification:{uuid4().hex}"
    try:
        async with factory() as session:
            student = await session.scalar(select(User).where(User.username == f"{prefix}-user"))
            if student is None:
                raise RuntimeError("E2E student fixture does not exist")
            session.add(
                OutboxTask(
                    task_key=task_key,
                    task_type="NOTIFICATION",
                    college_id=student.college_id,
                    payload={
                        "user_id": student.id,
                        "college_id": student.college_id,
                        "title": title,
                        "content": f"Outbox 实时通知 {prefix}",
                    },
                    execute_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )
            await session.commit()
            result = {"taskKey": task_key, "userId": student.id, "title": title}
    finally:
        await engine.dispose()
    return result


async def duplicate_notification(prefix: str, title: str) -> dict[str, object]:
    settings = isolated_settings()
    engine = build_engine(settings)
    factory = build_session_factory(engine)
    redis = from_url(settings.redis_url, decode_responses=True)
    try:
        async with factory() as session:
            student = await session.scalar(select(User).where(User.username == f"{prefix}-user"))
            if student is None:
                raise RuntimeError("E2E student fixture does not exist")
            notification = await session.scalar(
                select(Notification)
                .where(Notification.user_id == student.id, Notification.title == title)
                .order_by(Notification.delivery_sequence.desc())
                .limit(1)
            )
            if notification is None:
                raise RuntimeError("notification to duplicate does not exist")
            payload = _event(notification)
            message_id = await redis.xadd(
                RedisNotificationRelay.STREAM,
                {
                    "user_id": str(student.id),
                    "payload": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    "source_task_key": f"e2e:{prefix}:duplicate:{notification.id}",
                },
            )
            return {
                "notificationId": notification.id,
                "deliverySequence": notification.delivery_sequence,
                "streamId": message_id,
                "title": title,
            }
    finally:
        await redis.aclose()
        await engine.dispose()


async def inject_sequence_gap(prefix: str) -> dict[str, object]:
    settings = isolated_settings()
    engine = build_engine(settings)
    factory = build_session_factory(engine)
    try:
        async with factory() as session:
            student = await session.scalar(select(User).where(User.username == f"{prefix}-user"))
            if student is None:
                raise RuntimeError("E2E student fixture does not exist")
            college_id = student.college_id
            now = datetime.now(UTC).replace(tzinfo=None)
            missing_sequence = await next_delivery_sequence(session, student.id)
            missing = Notification(
                user_id=student.id,
                college_id=college_id,
                type="SYSTEM",
                title=f"序号缺口补齐 {prefix} · 缺失",
                content="这条通知保留在 MySQL，没有投递到 Redis Stream。",
                delivery_sequence=missing_sequence,
                created_at=now,
                updated_at=now,
            )
            session.add(missing)
            later_sequence = await next_delivery_sequence(session, student.id)
            later = Notification(
                user_id=student.id,
                college_id=college_id,
                type="SYSTEM",
                title=f"序号缺口补齐 {prefix} · 后续",
                content="该序号事件触发 SSE Hub 从 MySQL 补读缺失序号。",
                delivery_sequence=later_sequence,
                created_at=now,
                updated_at=now,
            )
            session.add(later)
            await session.flush()
            missing_id = missing.id
            later_id = later.id
            later_payload = _event(later)
            await session.commit()
            user_id = student.id
    finally:
        await engine.dispose()

    redis = from_url(settings.redis_url, decode_responses=True)
    try:
        stream_id = await redis.xadd(
            RedisNotificationRelay.STREAM,
            {
                "user_id": str(user_id),
                "payload": json.dumps(later_payload, ensure_ascii=False, separators=(",", ":")),
                "source_task_key": f"e2e:{prefix}:gap-trigger:{later_id}",
            },
        )
    finally:
        await redis.aclose()
    return {
        "missingNotificationId": missing_id,
        "missingSequence": missing_sequence,
        "laterNotificationId": later_id,
        "laterSequence": later_sequence,
        "streamId": stream_id,
    }


async def notification_rows(prefix: str) -> list[dict[str, object]]:
    settings = Settings()
    engine = build_engine(settings)
    factory = build_session_factory(engine)
    try:
        async with factory() as session:
            student = await session.scalar(select(User).where(User.username == f"{prefix}-user"))
            if student is None:
                raise RuntimeError("E2E student fixture does not exist")
            rows = list(
                (
                    await session.scalars(
                        select(Notification)
                        .where(Notification.user_id == student.id)
                        .order_by(Notification.delivery_sequence.asc())
                    )
                ).all()
            )
            return [
                {
                    "id": row.id,
                    "userId": row.user_id,
                    "deliverySequence": row.delivery_sequence,
                    "title": row.title,
                    "isRead": row.is_read,
                }
                for row in rows
            ]
    finally:
        await engine.dispose()


async def _redis_for_prefix(prefix: str):
    settings = isolated_settings()
    redis = from_url(settings.redis_url, decode_responses=True)
    return settings, redis


async def inspect_stream(prefix: str, *, notification_id: int | None = None) -> dict[str, object]:
    settings, redis = await _redis_for_prefix(prefix)
    try:
        groups = await redis.xinfo_groups(RedisNotificationRelay.STREAM)
        group_stats = []
        for group in groups:
            name = str(group.get("name", ""))
            group_stats.append(
                {
                    "name": name,
                    "consumers": int(group.get("consumers", 0) or 0),
                    "pending": int(group.get("pending", 0) or 0),
                    "lag": int(group.get("lag", 0) or 0),
                    "lastDeliveredId": str(group.get("last-delivered-id", "0-0")),
                }
            )
        matching_entries = []
        if notification_id is not None:
            for message_id, fields in await redis.xrange(RedisNotificationRelay.STREAM):
                try:
                    payload = json.loads(str(fields.get("payload", "{}")))
                except json.JSONDecodeError:
                    continue
                if payload.get("id") == notification_id:
                    matching_entries.append(
                        {
                            "streamId": message_id,
                            "notificationId": notification_id,
                            "deliverySequence": payload.get("deliverySequence"),
                            "title": payload.get("title"),
                        }
                    )
        return {
            "stream": RedisNotificationRelay.STREAM,
            "streamLength": int(await redis.xlen(RedisNotificationRelay.STREAM)),
            "groups": group_stats,
            "deadLetterLength": int(await redis.xlen(RedisNotificationRelay.DEAD_LETTER_STREAM)),
            "matchingNotificationEntries": matching_entries,
        }
    finally:
        await redis.aclose()


async def create_stale_group(prefix: str) -> dict[str, object]:
    _settings, redis = await _redis_for_prefix(prefix)
    name = f"e2e:stale:{prefix}"
    try:
        created = await redis.xgroup_create(
            RedisNotificationRelay.STREAM,
            name,
            id="$",
            mkstream=True,
        )
        return {"created": bool(created), "groupName": name}
    finally:
        await redis.aclose()


async def set_backlog(prefix: str, user_id: int, count: int) -> dict[str, object]:
    settings, redis = await _redis_for_prefix(prefix)
    hold_key = f"{BACKLOG_HOLD_KEY_PREFIX}{prefix}:backlog-hold"
    try:
        await redis.set(hold_key, "1")
        first_id = ""
        last_id = ""
        for index in range(1, count + 1):
            message_id = await redis.xadd(
                RedisNotificationRelay.STREAM,
                {
                    "user_id": str(user_id),
                    "payload": json.dumps(
                        {
                            "eventType": "read_state_changed",
                            "userId": user_id,
                            "notificationId": None,
                            "all": False,
                        },
                        separators=(",", ":"),
                    ),
                    "source_task_key": f"e2e-backlog:{prefix}:{index}",
                },
            )
            first_id = first_id or message_id
            last_id = message_id
        return {
            "stream": RedisNotificationRelay.STREAM,
            "holdKey": hold_key,
            "count": count,
            "firstId": first_id,
            "lastId": last_id,
        }
    finally:
        await redis.aclose()


async def release_backlog(prefix: str) -> dict[str, object]:
    _settings, redis = await _redis_for_prefix(prefix)
    try:
        removed = await redis.delete(f"{BACKLOG_HOLD_KEY_PREFIX}{prefix}:backlog-hold")
        return {"released": bool(removed)}
    finally:
        await redis.aclose()


async def publish_read_state(prefix: str, user_id: int, *, hold: bool = False) -> dict[str, object]:
    settings, redis = await _redis_for_prefix(prefix)
    try:
        source = f"e2e-backlog:{prefix}:trim-check" if hold else f"e2e:{prefix}:trim-check"
        if hold:
            await redis.set(f"{BACKLOG_HOLD_KEY_PREFIX}{prefix}:backlog-hold", "1")
        message_id = await redis.xadd(
            RedisNotificationRelay.STREAM,
            {
                "user_id": str(user_id),
                "payload": json.dumps(
                    {
                        "eventType": "read_state_changed",
                        "userId": user_id,
                        "notificationId": None,
                        "all": False,
                    },
                    separators=(",", ":"),
                ),
                "source_task_key": source,
            },
        )
        return {"streamId": message_id, "sourceTaskKey": source}
    finally:
        await redis.aclose()


async def main_async(args: argparse.Namespace) -> object:
    prefix = validate_prefix(args.prefix)
    if args.action == "enqueue":
        return await enqueue_notification(prefix, args.title or "")
    if args.action == "duplicate":
        return await duplicate_notification(prefix, args.title or "")
    if args.action == "gap":
        return await inject_sequence_gap(prefix)
    if args.action == "rows":
        return await notification_rows(prefix)
    if args.action == "backlog":
        if not 1 <= args.count <= 5000:
            raise ValueError("backlog count must be between 1 and 5000")
        if args.user_id is None:
            raise ValueError("--user-id is required for backlog injection")
        return await set_backlog(prefix, args.user_id, args.count)
    if args.action == "release-backlog":
        return await release_backlog(prefix)
    if args.action == "publish-read-state":
        if args.user_id is None:
            raise ValueError("--user-id is required")
        return await publish_read_state(prefix, args.user_id, hold=args.hold)
    if args.action == "inspect-stream":
        return await inspect_stream(prefix, notification_id=args.notification_id)
    if args.action == "create-stale-group":
        return await create_stale_group(prefix)
    raise ValueError(f"unsupported action: {args.action}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=(
            "enqueue",
            "duplicate",
            "gap",
            "rows",
            "backlog",
            "release-backlog",
            "publish-read-state",
            "inspect-stream",
            "create-stale-group",
        ),
    )
    parser.add_argument("--prefix", required=True, type=validate_prefix)
    parser.add_argument("--title")
    parser.add_argument("--count", type=int, default=1105)
    parser.add_argument("--user-id", type=int)
    parser.add_argument("--notification-id", type=int)
    parser.add_argument("--hold", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(main_async(args))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
