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
        self._lock = asyncio.Lock()

    async def connect(self, user_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[user_id].add(websocket)

    async def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        async with self._lock:
            connections = self._connections.get(user_id)
            if not connections:
                return
            connections.discard(websocket)
            if not connections:
                self._connections.pop(user_id, None)

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
