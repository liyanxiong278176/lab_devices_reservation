from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime
from urllib.parse import urlsplit

from fastapi import Depends, Request

from app.auth.sessions import refresh_token_session_id
from app.core.errors import ApiError
from app.core.settings import Settings

CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_ANONYMOUS_SESSION = "anon"
CSRF_MAX_AGE_SECONDS = 7 * 24 * 60 * 60


def _csrf_key(settings: Settings) -> bytes:
    return hmac.new(
        settings.jwt_secret.encode("utf-8"),
        b"labflow:csrf-token:v1",
        hashlib.sha256,
    ).digest()


def issue_csrf_token(settings: Settings, session_id: str) -> str:
    nonce = secrets.token_urlsafe(24)
    issued_at = str(int(datetime.now(UTC).timestamp()))
    message = f"{session_id}.{nonce}.{issued_at}".encode("ascii")
    signature = hmac.new(_csrf_key(settings), message, hashlib.sha256).hexdigest()
    return f"{session_id}.{nonce}.{issued_at}.{signature}"


def csrf_token_session_id(settings: Settings, value: str | None) -> str | None:
    if not value:
        return None
    parts = value.split(".")
    if len(parts) != 4:
        return None
    session_id, nonce, issued_at_text, signature = parts
    if not session_id or len(nonce) < 20 or len(signature) != 64:
        return None
    try:
        issued_at = int(issued_at_text)
    except ValueError:
        return None
    now = int(datetime.now(UTC).timestamp())
    if issued_at > now + 60 or now - issued_at > CSRF_MAX_AGE_SECONDS:
        return None
    message = f"{session_id}.{nonce}.{issued_at_text}".encode("ascii")
    expected = hmac.new(_csrf_key(settings), message, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    return session_id


def _request_origin(request: Request) -> str | None:
    origin = request.headers.get("origin")
    candidate = origin or request.headers.get("referer")
    if not candidate:
        return None
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return None
    if not parsed.scheme or not parsed.netloc or parsed.username or parsed.password:
        return None
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def _trusted_origin(request: Request) -> bool:
    origin = _request_origin(request)
    if origin is None:
        return False
    return origin in {value.rstrip("/") for value in request.app.state.settings.cors_origins}


def _access_session_id(request: Request) -> str | None:
    from app.auth.security import decode_session_id

    token = request.cookies.get(request.app.state.settings.access_cookie_name)
    if not token:
        return None
    try:
        return decode_session_id(request, token, allow_expired=True)
    except ApiError:
        return None


def _csrf_session_id(request: Request) -> str | None:
    settings = request.app.state.settings
    access_sid = _access_session_id(request)
    if access_sid:
        return access_sid
    return refresh_token_session_id(request.cookies.get(settings.refresh_cookie_name))


async def enforce_csrf(request: Request) -> None:
    if request.method.upper() in {"GET", "HEAD", "OPTIONS", "TRACE"}:
        return
    if not _trusted_origin(request):
        raise ApiError("CSRF_ORIGIN_INVALID", "请求来源不受信任", 403)

    settings = request.app.state.settings
    cookie_value = request.cookies.get(settings.csrf_cookie_name)
    header_value = request.headers.get(CSRF_HEADER_NAME)
    if (
        not cookie_value
        or not header_value
        or not hmac.compare_digest(cookie_value, header_value)
    ):
        raise ApiError("CSRF_TOKEN_INVALID", "CSRF 校验失败，请刷新页面后重试", 403)

    csrf_sid = csrf_token_session_id(settings, cookie_value)
    if csrf_sid is None:
        raise ApiError("CSRF_TOKEN_INVALID", "CSRF 令牌无效或已过期", 403)

    path = request.url.path.rstrip("/")
    if path.endswith("/auth/refresh"):
        refresh_sid = refresh_token_session_id(request.cookies.get(settings.refresh_cookie_name))
        if refresh_sid is None or csrf_sid != refresh_sid:
            raise ApiError("CSRF_SESSION_MISMATCH", "CSRF 令牌与登录会话不匹配", 403)
        return

    if path.endswith("/auth/login") or path.endswith("/auth/register"):
        # A signed token from the current browser session is sufficient to
        # protect login against CSRF; the endpoint intentionally replaces it
        # with a new sid-bound token after successful authentication.
        return

    access_sid = _access_session_id(request)
    if access_sid is None or csrf_sid != access_sid:
        raise ApiError("CSRF_SESSION_MISMATCH", "CSRF 令牌与登录会话不匹配", 403)


csrf_dependency = Depends(enforce_csrf)
