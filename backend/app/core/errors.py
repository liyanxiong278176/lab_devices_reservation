import logging
from collections.abc import Mapping

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError
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


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    body = _error_body(request, exc.code, exc.message)
    body["data"] = exc.data
    return JSONResponse(
        status_code=exc.status_code,
        content=body,
        headers=exc.headers,
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled request error", exc_info=exc)
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)) or (
        isinstance(exc, DBAPIError) and exc.connection_invalidated
    ):
        return JSONResponse(
            status_code=503,
            content=_error_body(
                request,
                "DEPENDENCY_UNAVAILABLE",
                "数据库或基础依赖暂时不可用，请稍后重试",
            ),
        )
    return JSONResponse(
        status_code=500,
        content=_error_body(request, "INTERNAL_ERROR", "服务暂时不可用，请稍后重试"),
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
    return JSONResponse(
        status_code=422,
        content={
            **_error_body(request, "VALIDATION_ERROR", "请求参数校验失败"),
            "data": {"errors": exc.errors()},
        },
    )
