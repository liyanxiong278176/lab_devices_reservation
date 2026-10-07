from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.core.settings import Settings
from app.infrastructure.db.models import Notification, OutboxTask
from app.infrastructure.notifications.realtime import NotificationHub
from app.infrastructure.notifications.relay import RedisNotificationRelay
from app.infrastructure.notifications.stream_ops import _replay, _trim_acked
from app.infrastructure.tasks.worker import OutboxWorker
from fastapi import FastAPI
from redis.asyncio import from_url
from redis.exceptions import ResponseError
from sqlalchemy import select


def _id_tuple(value: str) -> tuple[int, int]:
    major, minor = value.split("-", maxsplit=1)
    return int(major), int(minor)


async def connect_user(hub: NotificationHub, user_id: int, session_id: str) -> object:
    stream = await hub.reserve_pending("192.0.2.10", max_pending=10, max_per_ip=10)
    assert stream is not None
    assert await hub.connect(user_id, stream, max_total=10, max_per_user=5, session_id=session_id)
    return stream


class MemoryRedisBroker:
    """Small Redis Streams fake covering group fan-out and pending recovery."""

    def __init__(self) -> None:
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self.groups: dict[tuple[str, str], dict[str, object]] = {}
        self.dead_letter_markers: set[str] = set()
        self.hashes: dict[str, dict[str, str]] = {}
        self.condition = asyncio.Condition()
        self.counter = 0

    def client(self) -> MemoryRedisClient:
        return MemoryRedisClient(self)

    def _stream(self, key: str) -> list[tuple[str, dict[str, str]]]:
        return self.streams.setdefault(key, [])

    async def append(self, key: str, fields: dict[str, str]) -> str:
        async with self.condition:
            self.counter += 1
            message_id = f"{self.counter}-0"
            self._stream(key).append((message_id, dict(fields)))
            self.condition.notify_all()
            return message_id

    def _group(self, key: str, group: str) -> dict[str, object]:
        return self.groups[(key, group)]


class MemoryRedisClient:
    def __init__(self, broker: MemoryRedisBroker) -> None:
        self.broker = broker

    async def xadd(self, key: str, fields: dict[str, str]) -> str:
        return await self.broker.append(key, fields)

    async def xgroup_create(
        self,
        key: str,
        group: str,
        *,
        id: str = "0-0",
        mkstream: bool = False,
    ) -> bool:
        if (key, group) in self.broker.groups:
            raise ResponseError("BUSYGROUP Consumer Group name already exists")
        if mkstream:
            entries = self.broker._stream(key)
        else:
            entries = self.broker.streams.get(key, [])
        last_id = entries[-1][0] if id == "$" and entries else "0-0" if id == "$" else id
        self.broker.groups[(key, group)] = {
            "last": last_id,
            "pending": {},
            "consumer_names": set(),
        }
        return True

    async def xreadgroup(
        self,
        groupname: str,
        consumername: str,
        streams: dict[str, str],
        *,
        count: int = 1,
        block: int | None = None,
    ) -> list[tuple[str, list[tuple[str, dict[str, str]]]]]:
        key = next(iter(streams))
        group = self.broker._group(key, groupname)
        group["consumer_names"].add(consumername)

        async def available():
            entries = self.broker._stream(key)
            last = str(group["last"])
            result = [entry for entry in entries if _id_tuple(entry[0]) > _id_tuple(last)][:count]
            if result:
                pending = group["pending"]
                assert isinstance(pending, dict)
                for message_id, _fields in result:
                    pending[message_id] = {
                        "consumer": consumername,
                        "delivered_at": time.monotonic(),
                        "deliveries": 1,
                    }
                group["last"] = result[-1][0]
                return [(key, result)]
            return []

        found = await available()
        if found or not block:
            return found
        try:
            async with self.broker.condition:
                await asyncio.wait_for(self.broker.condition.wait(), timeout=block / 1000)
        except TimeoutError:
            return []
        return await available()

    async def xpending_range(
        self,
        key: str,
        groupname: str,
        minimum: str,
        maximum: str,
        count: int,
    ) -> list[dict[str, object]]:
        pending = self.broker._group(key, groupname)["pending"]
        assert isinstance(pending, dict)
        entries = []
        for message_id in sorted(pending, key=_id_tuple):
            if minimum not in {"-", "+"} and _id_tuple(message_id) < _id_tuple(minimum):
                continue
            if maximum not in {"-", "+"} and _id_tuple(message_id) > _id_tuple(maximum):
                continue
            state = pending[message_id]
            entries.append(
                {
                    "message_id": message_id,
                    "consumer": state["consumer"],
                    "time_since_delivered": int(
                        (time.monotonic() - float(state["delivered_at"])) * 1000
                    ),
                    "times_delivered": int(state["deliveries"]),
                }
            )
            if len(entries) >= count:
                break
        return entries

    async def xclaim(
        self,
        key: str,
        groupname: str,
        consumername: str,
        min_idle_time: int,
        message_ids: list[str],
    ) -> list[tuple[str, dict[str, str]]]:
        group = self.broker._group(key, groupname)
        pending = group["pending"]
        assert isinstance(pending, dict)
        claimed = []
        for message_id in message_ids:
            state = pending.get(message_id)
            if state is None:
                continue
            idle_ms = int((time.monotonic() - float(state["delivered_at"])) * 1000)
            if idle_ms < min_idle_time:
                continue
            state["consumer"] = consumername
            state["delivered_at"] = time.monotonic()
            state["deliveries"] = int(state["deliveries"]) + 1
            stored = next(
                entry for entry in self.broker._stream(key) if entry[0] == message_id
            )
            claimed.append(stored)
        return claimed

    async def xack(self, key: str, groupname: str, message_id: str) -> int:
        pending = self.broker._group(key, groupname)["pending"]
        assert isinstance(pending, dict)
        return int(pending.pop(message_id, None) is not None)

    async def eval(self, script: str, numkeys: int, *values: str) -> int:
        del script
        assert numkeys == 3
        key, dead_letter, _dedupe, group, source_id, user_id, payload, task_key, attempts, error = (
            values
        )
        marker = f"{group}|{source_id}"
        if marker not in self.broker.dead_letter_markers:
            self.broker.dead_letter_markers.add(marker)
            await self.broker.append(
                dead_letter,
                {
                    "source_group": group,
                    "source_id": source_id,
                    "user_id": user_id,
                    "payload": payload,
                    "source_task_key": task_key,
                    "attempts": attempts,
                    "error": error,
                },
            )
        return await self.xack(key, group, source_id)

    async def xlen(self, key: str) -> int:
        return len(self.broker._stream(key))

    async def xinfo_groups(self, key: str) -> list[dict[str, object]]:
        result = []
        for (stream_key, name), group in self.broker.groups.items():
            if stream_key != key:
                continue
            last = str(group["last"])
            lag = sum(
                1
                for message_id, _fields in self.broker._stream(key)
                if _id_tuple(message_id) > _id_tuple(last)
            )
            pending = group["pending"]
            assert isinstance(pending, dict)
            result.append(
                {
                    "name": name,
                    "consumers": len(group["consumer_names"]),
                    "pending": len(pending),
                    "lag": lag,
                    "last-delivered-id": last,
                }
            )
        return result

    async def xrange(
        self,
        key: str,
        min: str = "-",
        max: str = "+",
        *,
        count: int | None = None,
    ) -> list[tuple[str, dict[str, str]]]:
        exact = min == max and min not in {"-", "+"}
        result = []
        for message_id, fields in self.broker._stream(key):
            if exact and message_id != min:
                continue
            if min.startswith("("):
                if _id_tuple(message_id) <= _id_tuple(min[1:]):
                    continue
            elif min not in {"-", "+"} and _id_tuple(message_id) < _id_tuple(min):
                continue
            if max not in {"-", "+"} and _id_tuple(message_id) > _id_tuple(max):
                continue
            result.append((message_id, fields))
            if count is not None and len(result) >= count:
                break
        return result

    async def xrevrange(
        self,
        key: str,
        *,
        max: str = "+",
        min: str = "-",
        count: int | None = None,
    ) -> list[tuple[str, dict[str, str]]]:
        return list(reversed(await self.xrange(key, min=min, max=max, count=count)))

    async def xdel(self, key: str, *message_ids: str) -> int:
        before = len(self.broker._stream(key))
        remove = set(message_ids)
        self.broker.streams[key] = [
            entry for entry in self.broker._stream(key) if entry[0] not in remove
        ]
        return before - len(self.broker._stream(key))

    async def hlen(self, key: str) -> int:
        return len(self.broker.hashes.get(key, {}))

    async def hget(self, key: str, field: str) -> str | None:
        return self.broker.hashes.get(key, {}).get(field)

    async def hset(self, key: str, field: str, value: str) -> int:
        values = self.broker.hashes.setdefault(key, {})
        is_new = field not in values
        values[field] = value
        return int(is_new)

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_outbox_notification_persists_sequence_then_wakes_stream(seeded) -> None:
    factory, _, _, student, _, _, _, _ = seeded
    hub = NotificationHub()
    stream = await connect_user(hub, student.id, "session-worker-test")
    app = FastAPI()
    app.state.settings = Settings(environment="test", cors_origins=[], enable_workers=False)
    app.state.session_factory = factory
    app.state.notification_hub = hub
    worker = OutboxWorker(app, poll_seconds=0.01)
    task_key = "test:notification:sse-durable-sequence"

    async with factory() as session:
        session.add(
            OutboxTask(
                task_key=task_key,
                task_type="NOTIFICATION",
                college_id=student.college_id,
                payload={
                    "user_id": student.id,
                    "college_id": student.college_id,
                    "title": "SSE 顺序通知",
                    "content": "通知应按用户序号从 MySQL 读取",
                },
                execute_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        await session.commit()

    assert await worker.run_once() is True
    assert await asyncio.wait_for(hub.take_pending(stream), timeout=1) == (True, False)
    async with factory() as session:
        notification = await session.scalar(
            select(Notification).where(Notification.source_task_key == task_key)
        )
        assert notification is not None
        assert notification.delivery_sequence == 1


@pytest.mark.asyncio
async def test_read_state_outbox_event_wakes_local_sse_hub(seeded) -> None:
    factory, _, _, student, _, _, _, _ = seeded
    hub = NotificationHub()
    stream = await connect_user(hub, student.id, "read-state-worker-test")
    app = FastAPI()
    app.state.settings = Settings(environment="test", cors_origins=[], enable_workers=False)
    app.state.session_factory = factory
    app.state.notification_hub = hub
    worker = OutboxWorker(app, poll_seconds=0.01)
    async with factory() as session:
        session.add(
            OutboxTask(
                task_key="test:notification:read-state",
                task_type="NOTIFICATION_READ_STATE",
                aggregate_key=f"notification-read-state:{student.id}",
                college_id=student.college_id,
                payload={"user_id": student.id, "notification_id": 99},
                execute_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        await session.commit()

    assert await worker.run_once() is True
    assert await hub.take_pending(stream) == (False, True)


@pytest.mark.asyncio
async def test_stream_groups_broadcast_full_events_to_each_api_process() -> None:
    broker = MemoryRedisBroker()
    hub_a = NotificationHub()
    hub_b = NotificationHub()
    stream_a = await connect_user(hub_a, 42, "a")
    stream_b = await connect_user(hub_b, 42, "b")
    other_user_stream = await connect_user(hub_b, 43, "other")
    client = broker.client()
    relay_a = RedisNotificationRelay(
        hub_a,
        client,
        "redis://unused",
        group_id="api-a",
        consumer=client,
    )
    relay_b = RedisNotificationRelay(
        hub_b,
        client,
        "redis://unused",
        group_id="api-b",
        consumer=client,
    )

    try:
        await asyncio.gather(relay_a.start(), relay_b.start())
        await hub_a.take_pending(stream_a)
        await hub_b.take_pending(stream_b)
        await hub_b.take_pending(other_user_stream)
        await relay_a.publish(
            42,
            {
                "eventType": "notification",
                "id": 81,
                "userId": 42,
                "deliverySequence": 12,
                "title": "完整通知事件",
            },
            task_key="notification:81",
        )
        await asyncio.wait_for(stream_b.wake.wait(), timeout=1)

        events_a, *_ = await hub_a.take_events(stream_a)
        events_b, *_ = await hub_b.take_events(stream_b)
        assert events_a[0]["title"] == "完整通知事件"
        assert events_b[0]["id"] == 81
        assert await hub_b.take_pending(other_user_stream) == (False, False)
        assert len(broker.groups) == 2
        assert all(not group["pending"] for group in broker.groups.values())
    finally:
        await asyncio.gather(relay_a.stop(), relay_b.stop())


@pytest.mark.asyncio
async def test_stream_broadcasts_read_state_events() -> None:
    broker = MemoryRedisBroker()
    hub_a = NotificationHub()
    hub_b = NotificationHub()
    stream_a = await connect_user(hub_a, 42, "a")
    stream_b = await connect_user(hub_b, 42, "b")
    client = broker.client()
    relay_a = RedisNotificationRelay(
        hub_a, client, "redis://unused", group_id="read-a", consumer=client
    )
    relay_b = RedisNotificationRelay(
        hub_b, client, "redis://unused", group_id="read-b", consumer=client
    )

    try:
        await asyncio.gather(relay_a.start(), relay_b.start())
        await hub_a.take_pending(stream_a)
        await hub_b.take_pending(stream_b)
        await relay_a.publish(
            42,
            {"eventType": "read_state_changed", "userId": 42, "notificationId": 81},
            task_key="notification:read-state:42:81",
        )
        await asyncio.wait_for(stream_b.wake.wait(), timeout=1)
        assert await hub_a.take_pending(stream_a) == (False, True)
        assert await hub_b.take_pending(stream_b) == (False, True)
    finally:
        await asyncio.gather(relay_a.stop(), relay_b.stop())


@pytest.mark.asyncio
async def test_new_group_triggers_mysql_reconciliation_instead_of_replaying_old_stream() -> None:
    broker = MemoryRedisBroker()
    client = broker.client()
    await client.xadd(
        RedisNotificationRelay.STREAM,
        {
            "user_id": "42",
            "payload": '{"eventType":"notification","id":81,"deliverySequence":12}',
            "source_task_key": "old-event",
        },
    )
    hub = NotificationHub()
    stream = await connect_user(hub, 42, "new-group")
    relay = RedisNotificationRelay(
        hub,
        client,
        "redis://unused",
        group_id="new-process",
        consumer=client,
    )

    try:
        await relay.start()
        assert await hub.take_pending(stream) == (True, False)
        assert await client.xpending_range(relay.STREAM, relay.group_name, "-", "+", 10) == []
        groups = await client.xinfo_groups(relay.STREAM)
        assert groups[0]["lag"] == 0
    finally:
        await relay.stop()


class FlakyHub(NotificationHub):
    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures
        self.calls = 0

    async def publish(self, user_id: int, payload: dict[str, object]) -> int:
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("temporary hub failure")
        return await super().publish(user_id, payload)


@pytest.mark.asyncio
async def test_stream_retries_pending_delivery_and_acks_after_hub_handoff() -> None:
    broker = MemoryRedisBroker()
    hub = FlakyHub(failures=1)
    target = await connect_user(hub, 50, "retry")
    client = broker.client()
    relay = RedisNotificationRelay(
        hub,
        client,
        "redis://unused",
        group_id="retry",
        consumer=client,
        retry_base_seconds=0.01,
    )
    try:
        await relay.start()
        await hub.take_pending(target)
        await relay.publish(
            50,
            {"eventType": "notification", "id": 5, "userId": 50, "deliverySequence": 1},
        )
        await asyncio.wait_for(target.wake.wait(), timeout=2)
        events, *_ = await hub.take_events(target)
        assert events[0]["id"] == 5
        assert hub.calls == 2
        assert await client.xpending_range(relay.STREAM, relay.group_name, "-", "+", 10) == []
    finally:
        await relay.stop()


@pytest.mark.asyncio
async def test_stream_sends_fifth_failed_attempt_to_dead_letter() -> None:
    broker = MemoryRedisBroker()
    hub = FlakyHub(failures=100)
    client = broker.client()
    relay = RedisNotificationRelay(
        hub,
        client,
        "redis://unused",
        group_id="dead-letter",
        consumer=client,
        retry_base_seconds=0.001,
        max_attempts=5,
    )
    try:
        await relay.start()
        await relay.publish(
            51,
            {"eventType": "notification", "id": 6, "userId": 51, "deliverySequence": 1},
        )
        deadline = asyncio.get_running_loop().time() + 6
        while await client.xlen(relay.DEAD_LETTER_STREAM) == 0:
            if asyncio.get_running_loop().time() >= deadline:
                pytest.fail("message did not reach dead-letter stream")
            await asyncio.sleep(0.025)
        entry = (await client.xrange(relay.DEAD_LETTER_STREAM))[0][1]
        assert entry["attempts"] == "5"
        assert "temporary hub failure" in entry["error"]
        assert await client.xpending_range(relay.STREAM, relay.group_name, "-", "+", 10) == []
    finally:
        await relay.stop()


@pytest.mark.asyncio
async def test_ops_replay_is_idempotent_and_trim_skips_pending_messages() -> None:
    broker = MemoryRedisBroker()
    client = broker.client()
    dead_letter_id = await client.xadd(
        RedisNotificationRelay.DEAD_LETTER_STREAM,
        {
            "user_id": "63",
            "payload": '{"eventType":"read_state_changed","userId":63}',
            "source_task_key": "read:63:1",
            "error": "temporary failure",
        },
    )

    first_replay = await _replay(client, dead_letter_id)
    second_replay = await _replay(client, dead_letter_id)
    assert first_replay["alreadyReplayed"] is False
    assert second_replay["alreadyReplayed"] is True
    assert await client.xlen(RedisNotificationRelay.STREAM) == 1

    await client.xgroup_create(
        RedisNotificationRelay.STREAM,
        "ops-group",
        id="0-0",
        mkstream=True,
    )
    await client.xreadgroup(
        "ops-group",
        "ops-consumer",
        {RedisNotificationRelay.STREAM: ">"},
        count=1,
        block=1,
    )
    while_pending = await _trim_acked(client, 10)
    assert while_pending["deleted"] == 0
    await client.xack(RedisNotificationRelay.STREAM, "ops-group", first_replay["newStreamId"])
    after_ack = await _trim_acked(client, 10)
    assert after_ack["deleted"] == 1


@pytest.mark.asyncio
async def test_real_redis_stream_broadcasts_to_another_process() -> None:
    redis_url = os.getenv("LAB_TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("set LAB_TEST_REDIS_URL to run the real Redis Streams integration")

    user_id = 4_200_000 + uuid4().int % 100_000
    notification_id = 42_000_000 + uuid4().int % 100_000
    hub_a = NotificationHub()
    hub_b = NotificationHub()
    stream_a = await connect_user(hub_a, user_id, "real-a")
    stream_b = await connect_user(hub_b, user_id, "real-b")
    other_user = await connect_user(hub_b, user_id + 1, "other")
    publisher_a = from_url(redis_url, decode_responses=True, socket_connect_timeout=0.5)
    consumer_a = from_url(redis_url, decode_responses=True, socket_connect_timeout=0.5)
    publisher_b = from_url(redis_url, decode_responses=True, socket_connect_timeout=0.5)
    consumer_b = from_url(redis_url, decode_responses=True, socket_connect_timeout=0.5)
    relay_a = RedisNotificationRelay(
        hub_a,
        publisher_a,
        redis_url,
        group_id=f"real-a-{uuid4().hex}",
        consumer=consumer_a,
    )
    relay_b = RedisNotificationRelay(
        hub_b,
        publisher_b,
        redis_url,
        group_id=f"real-b-{uuid4().hex}",
        consumer=consumer_b,
    )

    try:
        await asyncio.gather(relay_a.start(), relay_b.start())
        await hub_a.take_pending(stream_a)
        await hub_b.take_pending(stream_b)
        await hub_b.take_pending(other_user)
        await relay_a.publish(
            user_id,
            {
                "eventType": "notification",
                "id": notification_id,
                "userId": user_id,
                "deliverySequence": 1,
            },
        )
        await asyncio.wait_for(stream_b.wake.wait(), timeout=2)
        assert (await hub_a.take_events(stream_a))[0][0]["id"] == notification_id
        assert (await hub_b.take_events(stream_b))[0][0]["id"] == notification_id
        assert await hub_b.take_pending(other_user) == (False, False)
    finally:
        await asyncio.gather(relay_a.stop(), relay_b.stop())
        await asyncio.gather(
            consumer_a.xgroup_destroy(relay_a.STREAM, relay_a.group_name),
            consumer_b.xgroup_destroy(relay_b.STREAM, relay_b.group_name),
        )
        await asyncio.gather(
            publisher_a.aclose(),
            consumer_a.aclose(),
            publisher_b.aclose(),
            consumer_b.aclose(),
        )
