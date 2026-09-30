import asyncio
from time import perf_counter
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
        queue_capacity: int = 0,
        exempt_paths: set[str] | None = None,
        bypass_paths: set[str] | None = None,
        exempt_capacity: int = 8,
    ) -> None:
        self.app = app
        self.gate = _AdmissionGate(capacity, queue_capacity)
        self.exempt_paths = exempt_paths or set()
        self.bypass_paths = bypass_paths or set()
        # Liveness checks should remain independent of DB-bound traffic, but
        # must not create an unbounded number of ASGI tasks under a probe flood.
        self.exempt_gate = _AdmissionGate(exempt_capacity, 0)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # A bounded long-lived stream owns its own connection admission in the
        # route layer and must not consume database request or health capacity.
        if scope.get("path") in self.bypass_paths:
            await self.app(scope, receive, send)
            return

        # Keep lightweight liveness routes independent from DB-bound traffic,
        # while still bounding them separately so a probe flood cannot exhaust
        # the event loop or leave thousands of sockets pending.
        is_exempt = scope.get("path") in self.exempt_paths
        gate = self.exempt_gate if is_exempt else self.gate
        started = perf_counter()
        # Bound active database work by the pool, but let a finite queue absorb
        # bursts instead of rejecting requests merely because all slots are busy.
        acquired = await gate.acquire()
        state: dict[str, Any] = scope.setdefault("state", {})
        state["admission_wait_seconds"] = perf_counter() - started
        state["admission_gate"] = "health" if is_exempt else "api"
        state["admission_result"] = "admitted" if acquired else "rejected"
        if not acquired:
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

        try:
            await self.app(scope, receive, send)
        finally:
            gate.release()


class _AdmissionGate:
    """A semaphore with an explicitly bounded, cancellation-safe wait queue."""

    def __init__(self, capacity: int, queue_capacity: int) -> None:
        self.semaphore = asyncio.Semaphore(max(1, capacity))
        self.queue_capacity = max(0, queue_capacity)
        self.waiting = 0
        self._lock = asyncio.Lock()

    async def acquire(self) -> bool:
        queued = False
        async with self._lock:
            if not self.semaphore.locked():
                # The guard prevents another request from claiming a free slot
                # between this check and the immediate semaphore acquire.
                await self.semaphore.acquire()
                return True
            if self.waiting >= self.queue_capacity:
                return False
            self.waiting += 1
            queued = True

        try:
            await self.semaphore.acquire()
            return True
        finally:
            if queued:
                async with self._lock:
                    self.waiting -= 1

    def release(self) -> None:
        self.semaphore.release()
