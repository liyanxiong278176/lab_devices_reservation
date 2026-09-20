from time import perf_counter
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach a traceable request ID to every response."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid4().hex
        request.state.request_id = request_id
        started = perf_counter()
        response = await call_next(request)
        metrics = getattr(request.app.state, "metrics", None)
        if metrics is not None:
            route = request.scope.get("route")
            metric_path = getattr(route, "path", request.url.path)
            metrics.increment(
                "http_requests_total",
                labels={
                    "method": request.method,
                    "path": metric_path,
                    "status": response.status_code,
                },
            )
            metrics.observe(
                "http_request_duration_ms",
                (perf_counter() - started) * 1000,
                labels={"method": request.method, "path": metric_path},
            )
        response.headers["X-Request-ID"] = request_id
        return response
