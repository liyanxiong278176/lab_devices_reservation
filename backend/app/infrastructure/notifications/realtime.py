from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from fastapi import WebSocket


class NotificationHub:
    """In-process notification fan-out for the single FastAPI service.

    The database notification row remains the source of truth.  A WebSocket
    is only a low-latency hint; reconnecting clients always reload history and
    unread counts over HTTP.  This makes delivery safe across reconnects and
    keeps the runtime compatible with the single-service decision.
    """

    def __init__(self) -> None:
        self._connections: defaultdict[int, set[WebSocket]] = defaultdict(set)
        self._session_ids: dict[WebSocket, str] = {}
        self._pending: dict[WebSocket, str] = {}
        self._lock = asyncio.Lock()

    async def reserve_pending(
        self,
        websocket: WebSocket,
        client_ip: str,
        *,
        max_pending: int,
        max_per_ip: int,
    ) -> bool:
        async with self._lock:
            if len(self._pending) >= max_pending:
                return False
            if sum(1 for ip in self._pending.values() if ip == client_ip) >= max_per_ip:
                return False
            self._pending[websocket] = client_ip
            return True

    async def connect(
        self,
        user_id: int,
        websocket: WebSocket,
        *,
        max_total: int,
        max_per_user: int,
        session_id: str | None = None,
    ) -> bool:
        async with self._lock:
            if websocket not in self._pending:
                return False
            if sum(map(len, self._connections.values())) >= max_total:
                self._pending.pop(websocket, None)
                return False
            if len(self._connections.get(user_id, ())) >= max_per_user:
                self._pending.pop(websocket, None)
                return False
            self._pending.pop(websocket, None)
            self._connections[user_id].add(websocket)
            if session_id:
                self._session_ids[websocket] = session_id
            return True

    async def disconnect_pending(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._pending.pop(websocket, None)

    async def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        async with self._lock:
            self._session_ids.pop(websocket, None)
            connections = self._connections.get(user_id)
            if not connections:
                return
            connections.discard(websocket)
            if not connections:
                self._connections.pop(user_id, None)

    async def disconnect_session(self, session_id: str) -> None:
        """Close live notification sockets authenticated by a revoked session."""
        targets: list[WebSocket] = []
        async with self._lock:
            for user_id, connections in list(self._connections.items()):
                for websocket in list(connections):
                    if self._session_ids.get(websocket) != session_id:
                        continue
                    connections.discard(websocket)
                    self._session_ids.pop(websocket, None)
                    targets.append(websocket)
                if not connections:
                    self._connections.pop(user_id, None)
        if targets:
            await asyncio.gather(
                *(websocket.close(code=4401) for websocket in targets),
                return_exceptions=True,
            )

    async def publish(self, user_id: int, payload: dict[str, Any]) -> None:
        async with self._lock:
            connections = list(self._connections.get(user_id, set()))
        stale: list[WebSocket] = []
        for websocket in connections:
            try:
                await websocket.send_json(payload)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            await self.disconnect(user_id, websocket)
