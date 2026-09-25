from time import perf_counter
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

_METRIC_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"})


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
            # Unknown paths are attacker-controlled; keep 404 metrics bounded.
            metric_path = getattr(route, "path", None) or "__unmatched__"
            raw_method = request.method
            metric_method = raw_method if raw_method in _METRIC_METHODS else "OTHER"
            status = response.status_code
            metric_status = status if 100 <= status <= 599 else 0
            metrics.increment(
                "http_requests_total",
                labels={
                    "method": metric_method,
                    "path": metric_path,
                    "status": metric_status,
                },
            )
            metrics.observe(
                "http_request_duration_ms",
                (perf_counter() - started) * 1000,
                labels={"method": metric_method, "path": metric_path},
            )
        response.headers["X-Request-ID"] = request_id
        return response
