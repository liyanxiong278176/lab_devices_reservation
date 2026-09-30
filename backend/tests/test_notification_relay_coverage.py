from __future__ import annotations

import asyncio
import json
from datetime import date

import pytest
from app.infrastructure.notifications import relay as relay_module
from app.infrastructure.notifications.relay import RedisNotificationRelay, _json_default
from redis.exceptions import RedisError


class Hub:
    def __init__(self) -> None:
        self.deliveries: list[tuple[int, dict[str, object]]] = []
        self.delivered = asyncio.Event()

    async def publish(self, user_id: int, payload: dict[str, object]) -> int:
        self.deliveries.append((user_id, payload))
        self.delivered.set()
        return 1


class Publisher:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.messages: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str) -> int:
        if self.error is not None:
            raise self.error
        self.messages.append((channel, message))
        return 2


class PubSub:
    def __init__(
        self, *, subscribe_error: Exception | None = None, close_error: Exception | None = None
    ):
        self.subscribe_error = subscribe_error
        self.close_error = close_error
        self.messages: asyncio.Queue[dict[str, object] | None] = asyncio.Queue()
        self.subscribed = asyncio.Event()
        self.closed = 0

    async def subscribe(self, _channel: str) -> None:
        self.subscribed.set()
        if self.subscribe_error is not None:
            raise self.subscribe_error

    async def get_message(self, **_kwargs: object) -> dict[str, object] | None:
        return await self.messages.get()

    async def aclose(self) -> None:
        self.closed += 1
        if self.close_error is not None:
            raise self.close_error


class Subscriber:
    def __init__(self, *pubsubs: PubSub) -> None:
        self.pubsubs = list(pubsubs)
        self.created = 0
        self.closed = 0

    def pubsub(self) -> PubSub:
        result = self.pubsubs[min(self.created, len(self.pubsubs) - 1)]
        self.created += 1
        return result

    async def aclose(self) -> None:
        self.closed += 1


@pytest.mark.asyncio
async def test_relay_delivers_valid_remote_envelopes_and_ignores_invalid_messages() -> None:
    hub = Hub()
    relay = RedisNotificationRelay(
        hub, Publisher(), "redis://unused", subscriber=Subscriber(PubSub())
    )

    await relay._deliver_remote(b"not a string")
    await relay._deliver_remote("{")
    await relay._deliver_remote("[]")
    await relay._deliver_remote(
        json.dumps({"origin": relay._instance_id, "user_id": 9, "payload": {"id": 1}})
    )
    await relay._deliver_remote(json.dumps({"origin": "remote", "user_id": True, "payload": {}}))
    await relay._deliver_remote(json.dumps({"origin": "remote", "user_id": 9, "payload": []}))
    await relay._deliver_remote(
        json.dumps({"origin": "remote", "user_id": 9, "payload": {"id": 2}})
    )

    assert hub.deliveries == [(9, {"id": 2})]
    with pytest.raises(TypeError, match="Unsupported realtime notification value"):
        _json_default(object())
    assert _json_default(date(2026, 9, 29)) == "2026-09-29"


@pytest.mark.asyncio
async def test_publish_keeps_local_delivery_and_propagates_redis_failure() -> None:
    hub = Hub()
    publisher = Publisher(RedisError("redis unavailable"))
    relay = RedisNotificationRelay(
        hub, publisher, "redis://unused", subscriber=Subscriber(PubSub())
    )

    with pytest.raises(RedisError):
        await relay.publish(7, {"id": 31})

    assert hub.deliveries == [(7, {"id": 31})]
    assert publisher.messages == []


@pytest.mark.asyncio
async def test_relay_start_is_idempotent_and_listener_retries_subscription() -> None:
    hub = Hub()
    first = PubSub(
        subscribe_error=RedisError("temporary subscribe failure"),
        close_error=RuntimeError("close failed"),
    )
    second = PubSub()
    subscriber = Subscriber(first, second)
    relay = RedisNotificationRelay(hub, Publisher(), "redis://unused", subscriber=subscriber)

    await relay.start(ready_timeout=1)
    await relay.start(ready_timeout=1)
    assert subscriber.created == 2

    await second.messages.put({"type": "subscribe", "data": "ignored"})
    await second.messages.put(
        {
            "type": "message",
            "data": json.dumps({"origin": "other-instance", "user_id": 15, "payload": {"id": 5}}),
        }
    )
    await asyncio.wait_for(hub.delivered.wait(), timeout=1)
    assert hub.deliveries == [(15, {"id": 5})]

    await relay.stop()
    assert second.closed >= 1
    assert subscriber.closed == 0  # The relay does not own the injected client.


@pytest.mark.asyncio
async def test_relay_start_timeout_and_owned_subscriber_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hub = Hub()
    blocked = PubSub()

    async def blocked_subscribe(channel: str) -> None:
        del channel
        await asyncio.Event().wait()

    blocked.subscribe = blocked_subscribe  # type: ignore[method-assign]
    subscriber = Subscriber(blocked)
    monkeypatch.setattr(relay_module, "from_url", lambda *_args, **_kwargs: subscriber)
    relay = RedisNotificationRelay(hub, Publisher(), "redis://owned")

    await relay.start(ready_timeout=0.001)
    assert relay._task is not None
    await relay.stop()
    assert blocked.closed >= 1
    assert subscriber.closed == 1


@pytest.mark.asyncio
async def test_stop_closes_current_pubsub_without_closing_injected_subscriber() -> None:
    pubsub = PubSub()
    subscriber = Subscriber(pubsub)
    relay = RedisNotificationRelay(Hub(), Publisher(), "redis://unused", subscriber=subscriber)
    relay._pubsub = pubsub

    await relay.stop()

    assert pubsub.closed == 1
    assert relay._pubsub is None
    assert subscriber.closed == 0


@pytest.mark.asyncio
async def test_listener_stops_after_subscription_failure_without_retrying() -> None:
    pubsub = PubSub()
    subscriber = Subscriber(pubsub)
    relay = RedisNotificationRelay(Hub(), Publisher(), "redis://unused", subscriber=subscriber)

    async def fail_and_stop(_channel: str) -> None:
        relay._stop.set()
        raise RedisError("subscription lost during shutdown")

    pubsub.subscribe = fail_and_stop  # type: ignore[method-assign]
    await relay._listen()

    assert subscriber.created == 1
    assert pubsub.closed == 2
    assert relay._pubsub is None


@pytest.mark.asyncio
async def test_listener_keeps_replacement_pubsub_reference_until_shutdown() -> None:
    pubsub = PubSub()
    subscriber = Subscriber(pubsub)
    relay = RedisNotificationRelay(Hub(), Publisher(), "redis://unused", subscriber=subscriber)
    replacement = object()

    async def replace_and_stop(_channel: str) -> None:
        relay._pubsub = replacement
        relay._stop.set()

    pubsub.subscribe = replace_and_stop  # type: ignore[method-assign]
    await relay._listen()

    assert pubsub.closed == 1
    assert relay._pubsub is replacement
