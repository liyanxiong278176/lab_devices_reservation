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
            metric_route = getattr(route, "path", None) or "__unmatched__"
            raw_method = request.method
            metric_method = raw_method if raw_method in _METRIC_METHODS else "OTHER"
            status = response.status_code
            # Mounted APIRouter routes expose a router-local path such as
            # ``/metrics``; compare the request URL so the prefixed scrape
            # endpoint is not counted as application traffic.
            metrics_path = f"{request.app.state.settings.api_prefix}/metrics"
            if request.url.path != metrics_path:
                metric_status_class = f"{status // 100}xx" if 100 <= status <= 599 else "other"
                admission_wait = max(
                    0.0,
                    float(getattr(request.state, "admission_wait_seconds", 0.0)),
                )
                admission_labels = {
                    "method": metric_method,
                    "route": metric_route,
                    "gate": getattr(request.state, "admission_gate", "unknown"),
                    "result": getattr(request.state, "admission_result", "unknown"),
                }
                metrics.increment(
                    "http_requests_total",
                    labels={
                        "method": metric_method,
                        "route": metric_route,
                        "status": str(status),
                        "status_class": metric_status_class,
                    },
                )
                metrics.observe(
                    "http_request_duration_seconds",
                    perf_counter() - started,
                    labels={"method": metric_method, "route": metric_route},
                )
                metrics.observe(
                    "http_request_admission_wait_seconds",
                    admission_wait,
                    labels=admission_labels,
                )
                metrics.observe(
                    "http_request_service_seconds",
                    max(0.0, perf_counter() - started - admission_wait),
                    labels={"method": metric_method, "route": metric_route},
                )
        response.headers["X-Request-ID"] = request_id
        return response
