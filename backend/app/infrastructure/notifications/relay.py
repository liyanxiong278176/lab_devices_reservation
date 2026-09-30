from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime
from typing import Any
from uuid import uuid4

from redis.asyncio import Redis, from_url
from redis.exceptions import RedisError

from app.infrastructure.notifications.realtime import NotificationHub

logger = logging.getLogger(__name__)


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Unsupported realtime notification value: {type(value).__name__}")


class RedisNotificationRelay:
    """Fan out notification wake-up hints to SSE connections on every process.

    The per-user stream cursor and notification contents live in MySQL. Redis
    Pub/Sub only wakes local streams to query committed rows in sequence order.
    """

    CHANNEL = "lab:v2:notification:fanout"

    def __init__(
        self,
        hub: NotificationHub,
        publisher: Redis,
        redis_url: str,
        *,
        socket_connect_timeout: float = 0.5,
        subscriber: Redis | None = None,
    ) -> None:
        self._hub = hub
        self._publisher = publisher
        self._subscriber = subscriber or from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=socket_connect_timeout,
            # A Pub/Sub connection must be allowed to wait for the next event.
            socket_timeout=None,
        )
        self._owns_subscriber = subscriber is None
        self._instance_id = uuid4().hex
        self._stop = asyncio.Event()
        self._ready = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._pubsub: Any | None = None

    async def start(self, *, ready_timeout: float = 1.0) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._listen(), name="notification-redis-relay")
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=ready_timeout)
        except TimeoutError:
            # Redis is an acceleration path. Keep the API available and retry
            # the subscription in the background while HTTP history remains
            # authoritative.
            logger.warning("notification Redis relay is not subscribed yet")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        if self._pubsub is not None:
            await self._pubsub.aclose()
            self._pubsub = None
        if self._owns_subscriber:
            await self._subscriber.aclose()

    async def publish(self, user_id: int, payload: dict[str, Any]) -> None:
        # Wake local streams first. The Redis subscriber ignores this process's
        # own envelope so a relay never creates duplicate SSE events.
        envelope = json.dumps(
            {"origin": self._instance_id, "user_id": user_id, "payload": payload},
            default=_json_default,
            separators=(",", ":"),
        )
        wire_envelope = json.loads(envelope)
        local_delivered = await self._hub.publish(user_id, wire_envelope["payload"])
        try:
            remote_subscribers = await self._publisher.publish(self.CHANNEL, envelope)
            logger.info(
                "notification fan-out published; notification_id=%s user_id=%s local=%s remote=%s",
                payload.get("id"),
                user_id,
                local_delivered,
                remote_subscribers,
            )
        except (RedisError, OSError, TimeoutError, ConnectionError) as exc:
            logger.warning(
                "notification Redis publish failed; durable history remains available (%s)",
                type(exc).__name__,
            )
            # Notification Outbox tasks retry this hint; duplicate wakes are
            # harmless because stream delivery is read from the MySQL cursor.
            raise

    async def _listen(self) -> None:
        retry_delay = 0.25
        while not self._stop.is_set():
            pubsub = self._subscriber.pubsub()
            self._pubsub = pubsub
            try:
                await pubsub.subscribe(self.CHANNEL)
                self._ready.set()
                retry_delay = 0.25
                while not self._stop.is_set():
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=1.0,
                    )
                    if message is None or message.get("type") != "message":
                        continue
                    await self._deliver_remote(message.get("data"))
            except asyncio.CancelledError:
                raise
            except (RedisError, OSError, TimeoutError, ConnectionError) as exc:
                self._ready.clear()
                logger.warning(
                    "notification Redis subscription interrupted; retrying (%s)",
                    type(exc).__name__,
                )
                try:
                    await pubsub.aclose()
                except Exception:
                    logger.debug("failed to close notification Pub/Sub connection", exc_info=True)
                if not self._stop.is_set():
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 10.0)
            finally:
                if self._pubsub is pubsub:
                    self._pubsub = None
                if self._stop.is_set():
                    await pubsub.aclose()

    async def _deliver_remote(self, raw: object) -> None:
        if not isinstance(raw, str):
            return
        try:
            envelope = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning("ignored malformed notification relay message")
            return
        if not isinstance(envelope, dict) or envelope.get("origin") == self._instance_id:
            return
        user_id = envelope.get("user_id")
        payload = envelope.get("payload")
        if (
            isinstance(user_id, bool)
            or not isinstance(user_id, int)
            or not isinstance(payload, dict)
        ):
            logger.warning("ignored invalid notification relay envelope")
            return
        delivered = await self._hub.publish(user_id, payload)
        logger.info(
            "notification stream wake-up received; event_type=%s user_id=%s streams=%s",
            payload.get("eventType"),
            user_id,
            delivered,
        )
