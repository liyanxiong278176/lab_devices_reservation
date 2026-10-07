from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from datetime import date, datetime
from typing import Any
from uuid import uuid4

from redis.asyncio import Redis, from_url
from redis.exceptions import RedisError, ResponseError

from app.infrastructure.notifications.realtime import NotificationHub

logger = logging.getLogger(__name__)


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Unsupported realtime notification value: {type(value).__name__}")


def _decode_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _field(mapping: dict[object, object], name: str, default: object = None) -> object:
    return mapping.get(name, mapping.get(name.encode(), default))


class PermanentNotificationMessageError(ValueError):
    """The event is malformed and retrying its payload cannot succeed."""


class RedisNotificationRelay:
    """Persist full notification events in Redis Streams and fan them to local SSE hubs.

    Every API process owns a distinct consumer group, so all processes receive
    every message while consumers inside one group can share the work. Stream
    ACK means the event reached this process's bounded in-memory SSE queues;
    browser reconnect and sequence-gap recovery still use MySQL.
    """

    STREAM = "lab:v2:notification:events"
    DEAD_LETTER_STREAM = "lab:v2:notification:dead-letter"
    DEAD_LETTER_DEDUPE = "lab:v2:notification:dead-letter:dedupe"
    DEAD_LETTER_REPLAYED = "lab:v2:notification:dead-letter:replayed"

    _DEAD_LETTER_SCRIPT = """
    local marker = ARGV[1] .. "|" .. ARGV[2]
    if redis.call("HEXISTS", KEYS[3], marker) == 0 then
        redis.call(
            "XADD", KEYS[2], "*",
            "source_group", ARGV[1],
            "source_id", ARGV[2],
            "user_id", ARGV[3],
            "payload", ARGV[4],
            "source_task_key", ARGV[5],
            "attempts", ARGV[6],
            "error", ARGV[7]
        )
        redis.call("HSET", KEYS[3], marker, "1")
    end
    return redis.call("XACK", KEYS[1], ARGV[1], ARGV[2])
    """

    def __init__(
        self,
        hub: NotificationHub,
        publisher: Redis,
        redis_url: str,
        *,
        group_id: str | None = None,
        consumer_concurrency: int = 4,
        max_attempts: int = 5,
        retry_base_seconds: float = 5.0,
        socket_connect_timeout: float = 0.5,
        consumer: Redis | None = None,
        consumer_name: str | None = None,
    ) -> None:
        if consumer_concurrency < 1:
            raise ValueError("consumer_concurrency must be positive")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if retry_base_seconds <= 0:
            raise ValueError("retry_base_seconds must be positive")
        self._hub = hub
        self._publisher = publisher
        self._consumer = consumer or from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=socket_connect_timeout,
            # XREADGROUP blocks while waiting for the next queued event.
            socket_timeout=None,
        )
        self._owns_consumer = consumer is None
        self.group_id = group_id or f"api-{uuid4().hex}"
        self.group_name = f"lab:v2:notification:process:{self.group_id}"
        self.consumer_name = consumer_name or f"consumer-{uuid4().hex}"
        self._consumer_concurrency = consumer_concurrency
        self._max_attempts = max_attempts
        self._retry_base_seconds = retry_base_seconds
        self._stop = asyncio.Event()
        self._ready = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._active: dict[str, asyncio.Task[None]] = {}
        self._metrics: object | None = None
        self._last_metrics_at = 0.0

    def set_metrics(self, metrics: object | None) -> None:
        self._metrics = metrics

    async def start(self, *, ready_timeout: float = 1.0) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="notification-stream-consumer")
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=ready_timeout)
        except TimeoutError:
            # Outbox rows stay durable if Redis is unavailable; the consumer
            # retries group creation in the background after the API starts.
            logger.warning("notification Stream consumer is not ready yet")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        tasks = tuple(self._active.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._active.clear()
        if self._owns_consumer:
            await self._consumer.aclose()

    async def publish(
        self,
        user_id: int,
        payload: dict[str, Any],
        *,
        task_key: str | None = None,
    ) -> str:
        """Append the complete committed event; producer retries may append duplicates."""
        event_type = payload.get("eventType")
        if event_type not in {"notification", "read_state_changed"}:
            raise ValueError("unsupported notification Stream event type")
        serialized = json.dumps(
            payload,
            default=_json_default,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        stream_id = await self._publisher.xadd(
            self.STREAM,
            {
                "user_id": str(user_id),
                "payload": serialized,
                "source_task_key": task_key or "",
            },
        )
        logger.info(
            "notification event appended to Redis Stream; stream_id=%s event_type=%s user_id=%s",
            stream_id,
            event_type,
            user_id,
        )
        return _decode_text(stream_id)

    async def _run(self) -> None:
        retry_delay = 0.25
        while not self._stop.is_set():
            try:
                await self._ensure_group()
                self._ready.set()
                retry_delay = 0.25
                await self._consume_group()
            except asyncio.CancelledError:
                raise
            except (RedisError, OSError, TimeoutError, ConnectionError):
                self._ready.clear()
                logger.warning(
                    "notification Stream connection interrupted; retrying",
                    exc_info=True,
                )
                await self._wait_or_stop(retry_delay)
                retry_delay = min(retry_delay * 2, 10.0)
            except Exception:
                self._ready.clear()
                logger.exception("notification Stream consumer failed; retrying")
                await self._wait_or_stop(retry_delay)
                retry_delay = min(retry_delay * 2, 10.0)
            finally:
                self._cancel_active()

    async def _ensure_group(self) -> None:
        try:
            # Existing groups retain their lag and PEL across process restarts.
            # A genuinely new process group starts at the tail; current local
            # SSE streams reconcile the pre-existing range from MySQL below.
            await self._consumer.xgroup_create(
                self.STREAM,
                self.group_name,
                id="$",
                mkstream=True,
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise
        else:
            await self._hub.request_mysql_catch_up()

    async def _consume_group(self) -> None:
        while not self._stop.is_set():
            await self._collect_finished_tasks()
            await self._sample_metrics_if_due()
            available = self._consumer_concurrency - len(self._active)
            if available <= 0:
                if self._active:
                    await asyncio.wait(
                        self._active.values(),
                        timeout=0.2,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                continue

            claimed = await self._claim_due_pending(available, set(self._active))
            if claimed:
                for message_id, fields, attempt in claimed:
                    self._schedule(message_id, fields, attempt)
                continue

            response = await self._consumer.xreadgroup(
                self.group_name,
                self.consumer_name,
                {self.STREAM: ">"},
                count=available,
                block=500,
            )
            for _stream_name, entries in response or ():
                for message_id, fields in entries:
                    normalized_id = _decode_text(message_id)
                    self._schedule(normalized_id, fields, 1)

    def _schedule(self, message_id: str, fields: dict[object, object], attempt: int) -> None:
        self._active[message_id] = asyncio.create_task(
            self._process_message(message_id, fields, attempt),
            name=f"notification-stream-{message_id}",
        )

    async def _collect_finished_tasks(self) -> None:
        finished = [message_id for message_id, task in self._active.items() if task.done()]
        for message_id in finished:
            task = self._active.pop(message_id)
            try:
                task.result()
            except asyncio.CancelledError:
                pass
            except Exception:
                # The pending entry remains recoverable even if ACK/DLQ failed.
                logger.exception(
                    "notification Stream message task escaped; stream_id=%s",
                    message_id,
                )

    def _cancel_active(self) -> None:
        for task in self._active.values():
            task.cancel()

    async def _claim_due_pending(
        self,
        limit: int,
        active_ids: set[str],
    ) -> list[tuple[str, dict[object, object], int]]:
        pending = await self._consumer.xpending_range(
            self.STREAM,
            self.group_name,
            "-",
            "+",
            max(100, limit * 16),
        )
        claimed: list[tuple[str, dict[object, object], int]] = []
        for entry in pending:
            message_id = _decode_text(_field(entry, "message_id", ""))
            if not message_id or message_id in active_ids:
                continue
            delivered = int(_field(entry, "times_delivered", 1) or 1)
            idle_ms = int(_field(entry, "time_since_delivered", 0) or 0)
            delay_ms = int(self._retry_delay_seconds(delivered, message_id) * 1000)
            if idle_ms < delay_ms:
                continue
            reclaimed = await self._consumer.xclaim(
                self.STREAM,
                self.group_name,
                self.consumer_name,
                min_idle_time=0,
                message_ids=[message_id],
            )
            for claimed_id, fields in reclaimed:
                if delivered >= self._max_attempts:
                    await self._dead_letter(
                        _decode_text(claimed_id),
                        fields,
                        delivered,
                        "maximum delivery attempts reached after an interrupted attempt",
                    )
                else:
                    claimed.append((_decode_text(claimed_id), fields, delivered + 1))
                    if len(claimed) >= limit:
                        return claimed
        return claimed

    def _retry_delay_seconds(self, attempt: int, message_id: str) -> float:
        exponent = min(max(0, attempt - 1), 10)
        base = min(3600.0, self._retry_base_seconds * (2**exponent))
        digest = hashlib.sha256(f"{self.group_name}:{message_id}".encode()).digest()
        jitter = 0.75 + int.from_bytes(digest[:2], "big") / 65535 * 0.5
        return base * jitter

    async def _process_message(
        self,
        message_id: str,
        fields: dict[object, object],
        attempt: int,
    ) -> None:
        raw_payload = _decode_text(_field(fields, "payload", ""))
        source_task_key = _decode_text(_field(fields, "source_task_key", ""))
        user_id: int | None = None
        try:
            user_id = self._parse_user_id(_field(fields, "user_id"))
            payload = self._parse_payload(raw_payload)
            payload.setdefault("userId", user_id)
            await self._hub.publish(user_id, payload)
            await self._consumer.xack(self.STREAM, self.group_name, message_id)
            self._metric_increment("notification_stream_acked_total")
        except asyncio.CancelledError:
            raise
        except PermanentNotificationMessageError as exc:
            await self._dead_letter(
                message_id,
                fields,
                attempt,
                str(exc),
                user_id=user_id,
                raw_payload=raw_payload,
                source_task_key=source_task_key,
            )
        except Exception as exc:
            if attempt >= self._max_attempts:
                await self._dead_letter(
                    message_id,
                    fields,
                    attempt,
                    f"{type(exc).__name__}: {exc}",
                    user_id=user_id,
                    raw_payload=raw_payload,
                    source_task_key=source_task_key,
                )
                return
            self._metric_increment("notification_stream_retries_total")
            logger.warning(
                "notification Stream handoff failed; stream_id=%s attempt=%s/%s error_type=%s",
                message_id,
                attempt,
                self._max_attempts,
                type(exc).__name__,
                exc_info=True,
            )

    @staticmethod
    def _parse_user_id(value: object) -> int:
        try:
            user_id = int(_decode_text(value))
        except (TypeError, ValueError) as exc:
            raise PermanentNotificationMessageError("invalid user_id") from exc
        if user_id <= 0:
            raise PermanentNotificationMessageError("invalid user_id")
        return user_id

    @staticmethod
    def _parse_payload(raw_payload: str) -> dict[str, Any]:
        try:
            payload = json.loads(raw_payload)
        except (json.JSONDecodeError, TypeError) as exc:
            raise PermanentNotificationMessageError("payload is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise PermanentNotificationMessageError("payload must be an object")
        if payload.get("eventType") not in {"notification", "read_state_changed"}:
            raise PermanentNotificationMessageError("unsupported eventType")
        if payload["eventType"] == "notification":
            for name in ("id", "deliverySequence"):
                value = payload.get(name)
                if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                    raise PermanentNotificationMessageError(f"invalid notification {name}")
        return payload

    async def _dead_letter(
        self,
        message_id: str,
        fields: dict[object, object],
        attempts: int,
        error: str,
        *,
        user_id: int | None = None,
        raw_payload: str | None = None,
        source_task_key: str | None = None,
    ) -> None:
        raw_payload = raw_payload or _decode_text(_field(fields, "payload", ""))
        source_task_key = source_task_key or _decode_text(
            _field(fields, "source_task_key", "")
        )
        if user_id is None:
            try:
                user_id = self._parse_user_id(_field(fields, "user_id"))
            except PermanentNotificationMessageError:
                user_id = 0
        await self._consumer.eval(
            self._DEAD_LETTER_SCRIPT,
            3,
            self.STREAM,
            self.DEAD_LETTER_STREAM,
            self.DEAD_LETTER_DEDUPE,
            self.group_name,
            message_id,
            str(user_id),
            raw_payload,
            source_task_key,
            str(attempts),
            error[:1000],
        )
        self._metric_increment("notification_stream_dead_letter_total")
        logger.error(
            "notification Stream message moved to dead letter; stream_id=%s group=%s attempts=%s",
            message_id,
            self.group_name,
            attempts,
        )
        await self._sample_metrics(force=True)

    async def _sample_metrics_if_due(self) -> None:
        now = asyncio.get_running_loop().time()
        if now - self._last_metrics_at >= 10:
            await self._sample_metrics(force=True)

    async def _sample_metrics(self, *, force: bool = False) -> None:
        metrics = self._metrics
        if metrics is None:
            return
        now = asyncio.get_running_loop().time()
        if not force and now - self._last_metrics_at < 10:
            return
        self._last_metrics_at = now
        try:
            stream_length = int(await self._consumer.xlen(self.STREAM))
            dead_letter_total = int(await self._consumer.xlen(self.DEAD_LETTER_STREAM))
            dead_letter_replayed = int(await self._consumer.hlen(self.DEAD_LETTER_REPLAYED))
            dead_letter_length = max(0, dead_letter_total - dead_letter_replayed)
            groups = await self._consumer.xinfo_groups(self.STREAM)
            own_group = next(
                (
                    group
                    for group in groups
                    if _decode_text(_field(group, "name", "")) == self.group_name
                ),
                None,
            )
            pending_count = int(_field(own_group or {}, "pending", 0) or 0)
            last_delivered_id = _decode_text(
                _field(own_group or {}, "last-delivered-id", "0-0")
            )
            raw_lag = _field(own_group or {}, "lag")
            lag = (
                int(raw_lag)
                if raw_lag is not None
                else int(
                    await self._consumer.execute_command(
                        "XCOUNT",
                        self.STREAM,
                        f"({last_delivered_id}",
                        "+",
                    )
                )
            )
            queued = (
                await self._consumer.xrange(
                    self.STREAM,
                    min=f"({last_delivered_id}",
                    max="+",
                    count=1,
                )
                if lag > 0
                else []
            )
            oldest_queued_age = 0.0
            if queued:
                timestamp = int(_decode_text(queued[0][0]).partition("-")[0]) / 1000
                oldest_queued_age = max(0.0, time.time() - timestamp)
            oldest_pending = await self._consumer.xpending_range(
                self.STREAM,
                self.group_name,
                "-",
                "+",
                1,
            )
            oldest_age = (
                int(_field(oldest_pending[0], "time_since_delivered", 0) or 0) / 1000
                if oldest_pending
                else 0.0
            )
            for name, value in (
                ("notification_stream_length", stream_length),
                ("notification_stream_group_lag", lag),
                ("notification_stream_oldest_queued_seconds", oldest_queued_age),
                ("notification_stream_pending", pending_count),
                ("notification_stream_oldest_pending_seconds", oldest_age),
                ("notification_stream_dead_letter_length", dead_letter_length),
            ):
                setter = getattr(metrics, "set_gauge", None)
                if setter is not None:
                    setter(name, value)
        except (RedisError, OSError, TimeoutError, ConnectionError):
            logger.warning("notification Stream metrics sampling failed", exc_info=True)

    def _metric_increment(self, name: str) -> None:
        increment = getattr(self._metrics, "increment", None)
        if increment is not None:
            increment(name)

    async def _wait_or_stop(self, delay: float) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=delay)
        except TimeoutError:
            pass
