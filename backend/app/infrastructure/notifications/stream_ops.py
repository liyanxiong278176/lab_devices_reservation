from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from redis.asyncio import from_url

from app.core.settings import Settings
from app.infrastructure.notifications.relay import (
    RedisNotificationRelay,
    _decode_text,
    _field,
)


def _stream_id(value: object) -> tuple[int, int]:
    major, separator, minor = _decode_text(value).partition("-")
    if not separator:
        raise ValueError(f"invalid Redis Stream id: {value}")
    return int(major), int(minor)


def _jsonable_entry(message_id: object, fields: dict[object, object]) -> dict[str, object]:
    result: dict[str, object] = {"id": _decode_text(message_id)}
    for key, value in fields.items():
        name = _decode_text(key)
        text = _decode_text(value)
        if name == "payload":
            try:
                result[name] = json.loads(text)
            except json.JSONDecodeError:
                result[name] = text
        else:
            result[name] = text
    return result


async def _stats(redis: Any) -> dict[str, object]:
    stream_length = int(await redis.xlen(RedisNotificationRelay.STREAM))
    groups = (
        await redis.xinfo_groups(RedisNotificationRelay.STREAM) if stream_length else []
    )
    group_stats = []
    for group in groups:
        name = _decode_text(_field(group, "name", ""))
        pending = int(_field(group, "pending", 0) or 0)
        oldest = await redis.xpending_range(
            RedisNotificationRelay.STREAM,
            name,
            "-",
            "+",
            1,
        )
        group_stats.append(
            {
                "name": name,
                "consumers": int(_field(group, "consumers", 0) or 0),
                "pending": pending,
                "lag": _field(group, "lag", 0),
                "oldestPendingIdleMs": (
                    int(_field(oldest[0], "time_since_delivered", 0) or 0)
                    if oldest
                    else 0
                ),
                "lastDeliveredId": _decode_text(
                    _field(group, "last-delivered-id", "0-0")
                ),
            }
        )
    dead_letter_total = int(await redis.xlen(RedisNotificationRelay.DEAD_LETTER_STREAM))
    dead_letter_replayed = int(await redis.hlen(RedisNotificationRelay.DEAD_LETTER_REPLAYED))
    return {
        "stream": RedisNotificationRelay.STREAM,
        "streamLength": stream_length,
        "groups": group_stats,
        "deadLetterStream": RedisNotificationRelay.DEAD_LETTER_STREAM,
        "deadLetterLength": dead_letter_total,
        "deadLetterUnresolved": max(0, dead_letter_total - dead_letter_replayed),
    }


async def _inspect(redis: Any, limit: int) -> list[dict[str, object]]:
    entries = await redis.xrevrange(
        RedisNotificationRelay.DEAD_LETTER_STREAM,
        max="+",
        min="-",
        count=limit,
    )
    inspected = []
    for message_id, fields in entries:
        entry = _jsonable_entry(message_id, fields)
        replayed_to = await redis.hget(RedisNotificationRelay.DEAD_LETTER_REPLAYED, entry["id"])
        if replayed_to is not None:
            entry["replayedTo"] = _decode_text(replayed_to)
        inspected.append(entry)
    return inspected


async def _replay(redis: Any, dead_letter_id: str) -> dict[str, object]:
    previous_stream_id = await redis.hget(
        RedisNotificationRelay.DEAD_LETTER_REPLAYED,
        dead_letter_id,
    )
    if previous_stream_id is not None:
        return {
            "replayedDeadLetterId": dead_letter_id,
            "newStreamId": _decode_text(previous_stream_id),
            "alreadyReplayed": True,
        }
    entries = await redis.xrange(
        RedisNotificationRelay.DEAD_LETTER_STREAM,
        min=dead_letter_id,
        max=dead_letter_id,
        count=1,
    )
    if not entries:
        raise ValueError(f"dead-letter entry not found: {dead_letter_id}")
    _message_id, fields = entries[0]
    user_id = _decode_text(_field(fields, "user_id", ""))
    payload = _decode_text(_field(fields, "payload", ""))
    decoded = json.loads(payload)
    if not isinstance(decoded, dict):
        raise ValueError("dead-letter payload must be a JSON object")
    stream_id = await redis.xadd(
        RedisNotificationRelay.STREAM,
        {
            "user_id": user_id,
            "payload": payload,
            "source_task_key": f"dlq-replay:{dead_letter_id}",
        },
    )
    normalized_stream_id = _decode_text(stream_id)
    await redis.hset(
        RedisNotificationRelay.DEAD_LETTER_REPLAYED,
        dead_letter_id,
        normalized_stream_id,
    )
    return {
        "replayedDeadLetterId": dead_letter_id,
        "newStreamId": normalized_stream_id,
        "alreadyReplayed": False,
    }


async def _trim_acked(redis: Any, limit: int) -> dict[str, object]:
    """Manually delete only entries delivered and ACKed by every existing group."""
    if int(await redis.xlen(RedisNotificationRelay.STREAM)) == 0:
        return {"examined": 0, "deleted": 0, "stream": RedisNotificationRelay.STREAM}
    groups = await redis.xinfo_groups(RedisNotificationRelay.STREAM)
    if not groups:
        raise ValueError("refusing to trim because the Stream has no consumer groups")
    entries = await redis.xrange(
        RedisNotificationRelay.STREAM,
        min="-",
        max="+",
        count=limit,
    )
    removable: list[str] = []
    for message_id, _fields in entries:
        normalized_id = _decode_text(message_id)
        safe = True
        for group in groups:
            group_name = _decode_text(_field(group, "name", ""))
            last_delivered = _decode_text(_field(group, "last-delivered-id", "0-0"))
            if _stream_id(last_delivered) < _stream_id(normalized_id):
                safe = False
                break
            pending = await redis.xpending_range(
                RedisNotificationRelay.STREAM,
                group_name,
                normalized_id,
                normalized_id,
                1,
            )
            if pending:
                safe = False
                break
        if safe:
            removable.append(normalized_id)
    deleted = int(await redis.xdel(RedisNotificationRelay.STREAM, *removable)) if removable else 0
    return {"examined": len(entries), "deleted": deleted, "stream": RedisNotificationRelay.STREAM}


async def _destroy_group(redis: Any, group_name: str) -> dict[str, object]:
    destroyed = bool(await redis.xgroup_destroy(RedisNotificationRelay.STREAM, group_name))
    if not destroyed:
        raise ValueError(f"consumer group not found: {group_name}")
    return {"destroyedGroup": group_name, "stream": RedisNotificationRelay.STREAM}


async def _run(args: argparse.Namespace) -> None:
    settings = Settings()
    redis = from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=settings.redis_socket_timeout_seconds,
        socket_timeout=5,
    )
    try:
        if args.command == "stats":
            result = await _stats(redis)
        elif args.command == "inspect":
            result = await _inspect(redis, args.limit)
        elif args.command == "replay":
            result = await _replay(redis, args.dead_letter_id)
        elif args.command == "destroy-group":
            result = await _destroy_group(redis, args.group_name)
        else:
            result = await _trim_acked(redis, args.limit)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    finally:
        await redis.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect and operate notification Redis Streams")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("stats", help="show Stream, consumer group, PEL and DLQ counters")
    inspect = subparsers.add_parser("inspect", help="show recent dead-letter messages")
    inspect.add_argument("--limit", type=int, default=50)
    replay = subparsers.add_parser("replay", help="requeue one dead-letter message")
    replay.add_argument("dead_letter_id")
    destroy = subparsers.add_parser(
        "destroy-group",
        help="remove a stale consumer group and its pending-entry list",
    )
    destroy.add_argument("group_name")
    destroy.add_argument("--confirm", action="store_true", required=True)
    trim = subparsers.add_parser(
        "trim-acked",
        help="manually delete oldest entries ACKed by all existing consumer groups",
    )
    trim.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()
    if getattr(args, "limit", 1) < 1:
        parser.error("--limit must be positive")
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
