import asyncio
from typing import Any

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class RequestCapacityMiddleware:
    """Bound concurrent HTTP work before authenticated routes acquire DB sessions."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        capacity: int,
        exempt_paths: set[str] | None = None,
        exempt_capacity: int = 8,
    ) -> None:
        self.app = app
        self.semaphore = asyncio.Semaphore(max(1, capacity))
        self.exempt_paths = exempt_paths or set()
        # Liveness checks should remain independent of DB-bound traffic, but
        # must not create an unbounded number of ASGI tasks under a probe flood.
        self.exempt_semaphore = asyncio.Semaphore(max(1, exempt_capacity))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Keep lightweight liveness routes independent from DB-bound traffic,
        # while still bounding them separately so a probe flood cannot exhaust
        # the event loop or leave thousands of sockets pending.
        semaphore = (
            self.exempt_semaphore if scope.get("path") in self.exempt_paths else self.semaphore
        )
        # Never queue an unbounded number of requests behind the connection
        # pool. Requests above the configured capacity fail fast.
        if semaphore.locked():
            state: dict[str, Any] = scope.get("state") or {}
            response = JSONResponse(
                status_code=503,
                content={
                    "code": "SERVICE_BUSY",
                    "message": "当前请求较多，请稍后重试",
                    "data": None,
                    "request_id": state.get("request_id"),
                },
                headers={"Retry-After": "1"},
            )
            await response(scope, receive, send)
            return

        await semaphore.acquire()
        try:
            await self.app(scope, receive, send)
        finally:
            semaphore.release()
