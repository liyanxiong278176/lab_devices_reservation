from __future__ import annotations

import asyncio
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(eq=False)
class NotificationStream:
    """One authenticated SSE connection with a bounded event queue."""

    client_ip: str
    user_id: int | None = None
    session_id: str | None = None
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    closed: asyncio.Event = field(default_factory=asyncio.Event)
    notification_pending: bool = False
    read_state_pending: bool = False
    notification_events: dict[int, dict[str, object]] = field(default_factory=dict)
    notification_overflow_sequence: int | None = None
    seen_notification_ids: set[int] = field(default_factory=set)
    recent_notification_ids: deque[int] = field(default_factory=deque)


class NotificationHub:
    """Bounded in-process registry for authenticated notification streams.

    Each local SSE connection has a bounded queue of full Stream events. The
    SSE endpoint emits them in per-user sequence order and reads MySQL only to
    fill a sequence gap or recover a reconnect.
    """

    def __init__(self, *, max_pending_events: int = 100) -> None:
        if max_pending_events < 1:
            raise ValueError("max_pending_events must be positive")
        self._max_pending_events = max_pending_events
        self._connections: defaultdict[int, set[NotificationStream]] = defaultdict(set)
        self._pending: set[NotificationStream] = set()
        self._lock = asyncio.Lock()

    async def reserve_pending(
        self,
        client_ip: str,
        *,
        max_pending: int,
        max_per_ip: int,
    ) -> NotificationStream | None:
        async with self._lock:
            if len(self._pending) >= max_pending:
                return None
            if sum(1 for stream in self._pending if stream.client_ip == client_ip) >= max_per_ip:
                return None
            stream = NotificationStream(client_ip=client_ip)
            self._pending.add(stream)
            return stream

    async def connect(
        self,
        user_id: int,
        stream: NotificationStream,
        *,
        max_total: int,
        max_per_user: int,
        session_id: str | None = None,
    ) -> bool:
        async with self._lock:
            if stream not in self._pending:
                return False
            total = sum(map(len, self._connections.values()))
            user_connections = self._connections.get(user_id, set())
            self._pending.discard(stream)
            if total >= max_total or len(user_connections) >= max_per_user:
                stream.closed.set()
                return False
            stream.user_id = user_id
            stream.session_id = session_id
            self._connections[user_id].add(stream)
            return True

    async def disconnect_pending(self, stream: NotificationStream) -> None:
        async with self._lock:
            self._pending.discard(stream)
            stream.closed.set()
            stream.wake.set()

    async def disconnect(self, user_id: int, stream: NotificationStream) -> None:
        async with self._lock:
            stream.closed.set()
            stream.wake.set()
            connections = self._connections.get(user_id)
            if not connections:
                return
            connections.discard(stream)
            if not connections:
                self._connections.pop(user_id, None)

    async def disconnect_session(self, session_id: str) -> None:
        """Close notification streams authenticated by a revoked session."""
        async with self._lock:
            targets = [
                stream
                for connections in self._connections.values()
                for stream in connections
                if stream.session_id == session_id
            ]
            for stream in targets:
                connections = self._connections.get(stream.user_id or -1)
                if connections is not None:
                    connections.discard(stream)
                    if not connections:
                        self._connections.pop(stream.user_id or -1, None)
                stream.closed.set()
                stream.wake.set()

    async def publish(self, user_id: int, payload: dict[str, object]) -> int:
        event_type = payload.get("eventType")
        async with self._lock:
            connections = tuple(self._connections.get(user_id, ()))
            for stream in connections:
                if event_type == "read_state_changed":
                    # A single refresh conveys the latest committed state even
                    # if several read operations arrive before the next tick.
                    stream.read_state_pending = True
                elif event_type == "notification":
                    stream.notification_pending = True
                    notification_id = payload.get("id")
                    sequence = payload.get("deliverySequence")
                    if (
                        isinstance(notification_id, int)
                        and not isinstance(notification_id, bool)
                        and notification_id in stream.seen_notification_ids
                    ):
                        stream.wake.set()
                        continue
                    if isinstance(notification_id, int) and not isinstance(notification_id, bool):
                        stream.seen_notification_ids.add(notification_id)
                        stream.recent_notification_ids.append(notification_id)
                        while len(stream.recent_notification_ids) > 1024:
                            expired_id = stream.recent_notification_ids.popleft()
                            stream.seen_notification_ids.discard(expired_id)
                    if (
                        isinstance(sequence, int)
                        and not isinstance(sequence, bool)
                        and sequence > 0
                    ):
                        if sequence not in stream.notification_events:
                            if len(stream.notification_events) >= self._max_pending_events:
                                stream.notification_events.clear()
                                stream.notification_overflow_sequence = max(
                                    sequence,
                                    stream.notification_overflow_sequence or 0,
                                )
                            elif stream.notification_overflow_sequence is None:
                                stream.notification_events[sequence] = dict(payload)
                        if stream.notification_overflow_sequence is not None:
                            stream.notification_overflow_sequence = max(
                                sequence, stream.notification_overflow_sequence
                            )
                stream.wake.set()
        return len(connections)

    async def request_mysql_catch_up(self) -> None:
        """Wake current SSE streams to reconcile events from before a new group existed."""
        async with self._lock:
            for connections in self._connections.values():
                for stream in connections:
                    stream.notification_pending = True
                    stream.wake.set()

    async def wait(self, stream: NotificationStream, timeout: float) -> bool:
        """Wait for a queued event or return False after the heartbeat interval."""
        if stream.closed.is_set():
            return True
        try:
            await asyncio.wait_for(stream.wake.wait(), timeout=timeout)
            return True
        except TimeoutError:
            return False

    async def take_pending(self, stream: NotificationStream) -> tuple[bool, bool]:
        events, read_state_pending, overflow_sequence, notification_pending = (
            await self.take_events(stream)
        )
        has_notification = bool(events) or overflow_sequence is not None or notification_pending
        return has_notification, read_state_pending

    async def take_events(
        self,
        stream: NotificationStream,
    ) -> tuple[list[dict[str, object]], bool, int | None, bool]:
        """Take queued full events, read-state state, and any overflow high-water mark."""
        async with self._lock:
            events = [stream.notification_events[key] for key in sorted(stream.notification_events)]
            fallback_notification_pending = (
                stream.notification_pending
                and not events
                and stream.notification_overflow_sequence is None
            )
            read_state_pending = stream.read_state_pending
            overflow_sequence = stream.notification_overflow_sequence
            stream.notification_events.clear()
            stream.notification_overflow_sequence = None
            stream.notification_pending = False
            stream.read_state_pending = False
            stream.wake.clear()
            return events, read_state_pending, overflow_sequence, fallback_notification_pending
