from __future__ import annotations

import asyncio
import json
from datetime import date

import pytest
from app.infrastructure.notifications.relay import (
    PermanentNotificationMessageError,
    RedisNotificationRelay,
    _json_default,
)
from redis.exceptions import RedisError, ResponseError


class Hub:
    async def publish(self, _user_id: int, _payload: dict[str, object]) -> int:
        return 0


class Publisher:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.entries: list[tuple[str, dict[str, str]]] = []

    async def xadd(self, stream: str, fields: dict[str, str]) -> str:
        if self.error is not None:
            raise self.error
        self.entries.append((stream, fields))
        return "1-0"


class Consumer:
    def __init__(
        self,
        *,
        create_errors: list[Exception] | None = None,
        busy_group: bool = False,
    ) -> None:
        self.create_errors = list(create_errors or [])
        self.busy_group = busy_group
        self.create_calls = 0
        self.closed = 0
        self.wait_forever = asyncio.Event()

    async def xgroup_create(self, *_args: object, **_kwargs: object) -> bool:
        self.create_calls += 1
        if self.create_errors:
            raise self.create_errors.pop(0)
        if self.busy_group:
            raise ResponseError("BUSYGROUP Consumer Group name already exists")
        return True

    async def xpending_range(self, *_args: object, **_kwargs: object) -> list[object]:
        return []

    async def xreadgroup(self, *_args: object, **_kwargs: object) -> list[object]:
        await self.wait_forever.wait()
        return []

    async def aclose(self) -> None:
        self.closed += 1


@pytest.mark.asyncio
async def test_publish_appends_full_event_to_stream() -> None:
    publisher = Publisher()
    consumer = Consumer()
    relay = RedisNotificationRelay(
        Hub(), publisher, "redis://unused", consumer=consumer, group_id="process-a"
    )

    stream_id = await relay.publish(
        9,
        {"eventType": "notification", "id": 17, "deliverySequence": 3},
        task_key="notification:17",
    )

    assert stream_id == "1-0"
    stream, fields = publisher.entries[0]
    assert stream == relay.STREAM
    assert fields["user_id"] == "9"
    assert json.loads(fields["payload"]) == {
        "eventType": "notification",
        "id": 17,
        "deliverySequence": 3,
    }
    assert fields["source_task_key"] == "notification:17"


@pytest.mark.asyncio
async def test_publish_rejects_unknown_event_and_propagates_redis_failure() -> None:
    publisher = Publisher(RedisError("redis unavailable"))
    relay = RedisNotificationRelay(Hub(), publisher, "redis://unused", consumer=Consumer())

    with pytest.raises(ValueError, match="unsupported notification Stream event type"):
        await relay.publish(7, {"eventType": "unknown"})
    with pytest.raises(RedisError, match="redis unavailable"):
        await relay.publish(7, {"eventType": "read_state_changed"})


def test_stream_event_validation_and_datetime_json_encoding() -> None:
    with pytest.raises(PermanentNotificationMessageError, match="not valid JSON"):
        RedisNotificationRelay._parse_payload("{")
    with pytest.raises(PermanentNotificationMessageError, match="unsupported eventType"):
        RedisNotificationRelay._parse_payload('{"eventType":"unknown"}')
    with pytest.raises(PermanentNotificationMessageError, match="invalid notification id"):
        RedisNotificationRelay._parse_payload(
            '{"eventType":"notification","id":true,"deliverySequence":1}'
        )
    assert _json_default(date(2026, 9, 29)) == "2026-09-29"
    with pytest.raises(TypeError, match="Unsupported realtime notification value"):
        _json_default(object())


@pytest.mark.asyncio
async def test_group_start_accepts_existing_group_and_preserves_injected_consumer() -> None:
    consumer = Consumer(busy_group=True)
    relay = RedisNotificationRelay(
        Hub(), Publisher(), "redis://unused", consumer=consumer, group_id="existing"
    )

    await relay.start(ready_timeout=1)
    assert relay._ready.is_set()
    assert relay.group_name.endswith(":existing")
    await relay.stop()

    assert consumer.create_calls == 1
    assert consumer.closed == 0


@pytest.mark.asyncio
async def test_start_timeout_retries_redis_and_closes_owned_consumer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    consumer = Consumer(create_errors=[RedisError("temporary outage")])
    monkeypatch.setattr(
        "app.infrastructure.notifications.relay.from_url",
        lambda *_args, **_kwargs: consumer,
    )
    relay = RedisNotificationRelay(Hub(), Publisher(), "redis://owned")

    await relay.start(ready_timeout=0.001)
    assert relay._task is not None
    await relay.stop()

    assert consumer.create_calls == 1
    assert consumer.closed == 1
