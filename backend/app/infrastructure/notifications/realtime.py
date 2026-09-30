from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(eq=False)
class NotificationStream:
    """One authenticated SSE connection and its coalesced wake-up state."""

    client_ip: str
    user_id: int | None = None
    session_id: str | None = None
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    closed: asyncio.Event = field(default_factory=asyncio.Event)
    notification_pending: bool = False
    read_state_pending: bool = False


class NotificationHub:
    """Bounded in-process registry for authenticated notification streams.

    Redis and Outbox messages only wake a stream. The stream then reads the
    durable MySQL rows by per-user sequence, so relay arrival order is irrelevant.
    """

    def __init__(self) -> None:
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
                else:
                    stream.notification_pending = True
                stream.wake.set()
        return len(connections)

    async def wait(self, stream: NotificationStream, timeout: float) -> bool:
        """Wait for a relay hint or return False after the heartbeat interval."""
        if stream.closed.is_set():
            return True
        try:
            await asyncio.wait_for(stream.wake.wait(), timeout=timeout)
            return True
        except TimeoutError:
            return False

    async def take_pending(self, stream: NotificationStream) -> tuple[bool, bool]:
        async with self._lock:
            notification_pending = stream.notification_pending
            read_state_pending = stream.read_state_pending
            stream.notification_pending = False
            stream.read_state_pending = False
            stream.wake.clear()
            return notification_pending, read_state_pending
