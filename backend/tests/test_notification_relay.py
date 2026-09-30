from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest
from app.core.settings import Settings
from app.infrastructure.db.models import Notification, OutboxTask
from app.infrastructure.notifications.realtime import NotificationHub
from app.infrastructure.notifications.relay import RedisNotificationRelay
from app.infrastructure.tasks.worker import OutboxWorker
from fastapi import FastAPI
from redis.asyncio import from_url
from sqlalchemy import select


async def connect_user(hub: NotificationHub, user_id: int, session_id: str) -> object:
    stream = await hub.reserve_pending("192.0.2.10", max_pending=10, max_per_ip=10)
    assert stream is not None
    assert await hub.connect(user_id, stream, max_total=10, max_per_user=5, session_id=session_id)
    return stream


class MemoryRedisBroker:
    def __init__(self) -> None:
        self.channels: dict[str, set[asyncio.Queue[dict[str, str]]]] = {}

    def client(self) -> MemoryRedisClient:
        return MemoryRedisClient(self)


class MemoryPubSub:
    def __init__(self, broker: MemoryRedisBroker) -> None:
        self.broker = broker
        self.queues: set[asyncio.Queue[dict[str, str]]] = set()

    async def subscribe(self, channel: str) -> None:
        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        self.queues.add(queue)
        self.broker.channels.setdefault(channel, set()).add(queue)

    async def get_message(
        self,
        *,
        ignore_subscribe_messages: bool = True,
        timeout: float = 1.0,
    ) -> dict[str, str] | None:
        del ignore_subscribe_messages
        try:
            return await asyncio.wait_for(next(iter(self.queues)).get(), timeout=timeout)
        except TimeoutError:
            return None

    async def aclose(self) -> None:
        for queues in self.broker.channels.values():
            queues.difference_update(self.queues)
        self.queues.clear()


class MemoryRedisClient:
    def __init__(self, broker: MemoryRedisBroker) -> None:
        self.broker = broker

    def pubsub(self) -> MemoryPubSub:
        return MemoryPubSub(self.broker)

    async def publish(self, channel: str, message: str) -> int:
        queues = self.broker.channels.get(channel, set())
        for queue in queues:
            queue.put_nowait({"type": "message", "data": message})
        return len(queues)

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
async def test_redis_relay_wakes_each_process_stream_once() -> None:
    broker = MemoryRedisBroker()
    hub_a = NotificationHub()
    hub_b = NotificationHub()
    stream_a = await connect_user(hub_a, 42, "a")
    stream_b = await connect_user(hub_b, 42, "b")
    other_user_stream = await connect_user(hub_b, 43, "other")
    client_a = broker.client()
    client_b = broker.client()
    relay_a = RedisNotificationRelay(hub_a, client_a, "redis://unused", subscriber=client_a)
    relay_b = RedisNotificationRelay(hub_b, client_b, "redis://unused", subscriber=client_b)

    try:
        await asyncio.gather(relay_a.start(), relay_b.start())
        await relay_a.publish(
            42,
            {"eventType": "notification", "id": 81, "deliverySequence": 12},
        )
        await asyncio.wait_for(stream_b.wake.wait(), timeout=1)

        assert await hub_a.take_pending(stream_a) == (True, False)
        assert await hub_b.take_pending(stream_b) == (True, False)
        assert await hub_b.take_pending(other_user_stream) == (False, False)
    finally:
        await asyncio.gather(relay_a.stop(), relay_b.stop())


@pytest.mark.asyncio
async def test_redis_relay_synchronizes_read_state_across_processes() -> None:
    broker = MemoryRedisBroker()
    hub_a = NotificationHub()
    hub_b = NotificationHub()
    stream_a = await connect_user(hub_a, 42, "a")
    stream_b = await connect_user(hub_b, 42, "b")
    client_a = broker.client()
    client_b = broker.client()
    relay_a = RedisNotificationRelay(hub_a, client_a, "redis://unused", subscriber=client_a)
    relay_b = RedisNotificationRelay(hub_b, client_b, "redis://unused", subscriber=client_b)

    try:
        await asyncio.gather(relay_a.start(), relay_b.start())
        await relay_a.publish(42, {"eventType": "read_state_changed", "notificationId": 81})
        await asyncio.wait_for(stream_b.wake.wait(), timeout=1)
        assert await hub_a.take_pending(stream_a) == (False, True)
        assert await hub_b.take_pending(stream_b) == (False, True)
    finally:
        await asyncio.gather(relay_a.stop(), relay_b.stop())


@pytest.mark.asyncio
async def test_real_redis_relay_wakes_another_process_stream() -> None:
    redis_url = os.getenv("LAB_TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("set LAB_TEST_REDIS_URL to run the real Redis relay integration")

    hub_a = NotificationHub()
    hub_b = NotificationHub()
    stream_a = await connect_user(hub_a, 4201, "real-a")
    stream_b = await connect_user(hub_b, 4201, "real-b")
    other_user = await connect_user(hub_b, 4202, "other")
    publisher_a = from_url(redis_url, decode_responses=True, socket_connect_timeout=0.5)
    publisher_b = from_url(redis_url, decode_responses=True, socket_connect_timeout=0.5)
    subscriber_a = from_url(
        redis_url, decode_responses=True, socket_connect_timeout=0.5, socket_timeout=None
    )
    subscriber_b = from_url(
        redis_url, decode_responses=True, socket_connect_timeout=0.5, socket_timeout=None
    )
    relay_a = RedisNotificationRelay(hub_a, publisher_a, redis_url, subscriber=subscriber_a)
    relay_b = RedisNotificationRelay(hub_b, publisher_b, redis_url, subscriber=subscriber_b)

    try:
        await asyncio.gather(relay_a.start(), relay_b.start())
        await relay_a.publish(4201, {"eventType": "notification", "id": 42001})
        await asyncio.wait_for(stream_b.wake.wait(), timeout=2)
        assert await hub_a.take_pending(stream_a) == (True, False)
        assert await hub_b.take_pending(stream_b) == (True, False)
        assert await hub_b.take_pending(other_user) == (False, False)
    finally:
        await asyncio.gather(relay_a.stop(), relay_b.stop())
        await asyncio.gather(publisher_a.aclose(), publisher_b.aclose())
