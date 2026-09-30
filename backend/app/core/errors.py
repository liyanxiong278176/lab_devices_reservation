import logging
from collections.abc import Mapping

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        data: object | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.data = data
        self.headers = dict(headers or {})


def _error_body(request: Request, code: str, message: str) -> dict[str, object]:
    return {
        "code": code,
        "message": message,
        "data": None,
        "request_id": getattr(request.state, "request_id", None),
    }


def _error_headers(
    request: Request,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    headers = dict(extra or {})
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        headers["X-Request-ID"] = request_id
    return headers


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    body = _error_body(request, exc.code, exc.message)
    body["data"] = exc.data
    return JSONResponse(
        status_code=exc.status_code,
        content=body,
        headers=exc.headers,
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, SQLAlchemyTimeoutError):
        logger.warning(
            "Request rejected because the database pool is full; request_id=%s",
            getattr(request.state, "request_id", None),
        )
        return JSONResponse(
            status_code=503,
            content=_error_body(request, "SERVICE_BUSY", "当前请求较多，请稍后重试"),
            headers=_error_headers(request, {"Retry-After": "1"}),
        )
    if isinstance(exc, (TimeoutError, ConnectionError, OSError, OperationalError)) or (
        isinstance(exc, DBAPIError) and exc.connection_invalidated
    ):
        # Connection establishment failures can have connection_invalidated=False
        # (for example asyncmy error 2013 while MySQL is restarting). Keep these
        # retryable without exposing driver/DSN details or emitting a traceback
        # every time a dependency is temporarily unavailable.
        logger.warning(
            "Request failed because a dependency is unavailable; request_id=%s error_type=%s",
            getattr(request.state, "request_id", None),
            type(exc).__name__,
        )
        return JSONResponse(
            status_code=503,
            content=_error_body(
                request,
                "DEPENDENCY_UNAVAILABLE",
                "数据库或基础依赖暂时不可用，请稍后重试",
            ),
            headers=_error_headers(request),
        )
    logger.exception("Unhandled request error", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content=_error_body(request, "INTERNAL_ERROR", "服务暂时不可用，请稍后重试"),
        headers=_error_headers(request),
    )


async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, Mapping):
        code = str(detail.get("code", "HTTP_ERROR"))
        message = str(detail.get("message", "request failed"))
    else:
        code = "HTTP_ERROR"
        message = str(detail)
    return JSONResponse(status_code=exc.status_code, content=_error_body(request, code, message))


async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    safe_errors = [
        {
            "loc": list(error.get("loc", ())),
            "msg": str(error.get("msg", "请求值无效")),
            "type": str(error.get("type", "value_error")),
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            **_error_body(request, "VALIDATION_ERROR", "请求参数校验失败"),
            "data": {"errors": safe_errors},
        },
    )
