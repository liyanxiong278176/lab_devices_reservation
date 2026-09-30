from __future__ import annotations

import hashlib
import hmac
import time
from types import SimpleNamespace

import app.auth.security as security
import pytest
from app.auth.csrf import (
    CSRF_HEADER_NAME,
    _csrf_key,
    _csrf_session_id,
    _request_origin,
    _trusted_origin,
    csrf_token_session_id,
    enforce_csrf,
    issue_csrf_token,
)
from app.core.errors import ApiError
from app.core.settings import Settings
from starlette.requests import Request

SESSION_ID = "s" * 43
SETTINGS = Settings(
    environment="test",
    _env_file=None,
    cors_origins=["https://trusted.example/"],
)


def signed_token(issued_at: int) -> str:
    nonce = "n" * 24
    message = f"{SESSION_ID}.{nonce}.{issued_at}".encode("ascii")
    signature = hmac.new(_csrf_key(SETTINGS), message, hashlib.sha256).hexdigest()
    return f"{SESSION_ID}.{nonce}.{issued_at}.{signature}"


def make_request(
    *,
    method: str = "POST",
    path: str = "/api/v2/reservations",
    origin: str | None = "https://trusted.example",
    referer: str | None = None,
    cookies: dict[str, str] | None = None,
    csrf_header: str | None = None,
) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    if referer is not None:
        headers.append((b"referer", referer.encode()))
    if csrf_header is not None:
        headers.append((CSRF_HEADER_NAME.lower().encode(), csrf_header.encode()))
    if cookies:
        encoded = "; ".join(f"{name}={value}" for name, value in cookies.items())
        headers.append((b"cookie", encoded.encode()))
    app = SimpleNamespace(state=SimpleNamespace(settings=SETTINGS))
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.0"},
            "http_version": "1.1",
            "server": ("testserver", 443),
            "client": ("127.0.0.1", 1234),
            "scheme": "https",
            "method": method,
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": headers,
            "app": app,
            "state": {},
        }
    )


def expect_code(error: pytest.ExceptionInfo[ApiError], code: str) -> None:
    assert error.value.code == code


def test_signed_csrf_tokens_validate_shape_signature_and_time_window() -> None:
    now = int(time.time())
    valid = issue_csrf_token(SETTINGS, SESSION_ID)
    assert csrf_token_session_id(SETTINGS, valid) == SESSION_ID
    assert csrf_token_session_id(SETTINGS, None) is None
    assert csrf_token_session_id(SETTINGS, "") is None
    assert csrf_token_session_id(SETTINGS, "a.b.c") is None
    assert csrf_token_session_id(SETTINGS, f".{ 'n' * 24}.{now}.{'0' * 64}") is None
    assert csrf_token_session_id(SETTINGS, f"{SESSION_ID}.short.{now}.{'0' * 64}") is None
    assert csrf_token_session_id(SETTINGS, f"{SESSION_ID}.{'n' * 24}.bad.{'0' * 64}") is None
    assert csrf_token_session_id(SETTINGS, signed_token(now + 61)) is None
    assert csrf_token_session_id(SETTINGS, signed_token(now - 7 * 24 * 60 * 60 - 1)) is None

    tampered = valid.rsplit(".", 1)
    invalid_signature = f"{tampered[0]}.{'0' * 64}"
    assert csrf_token_session_id(SETTINGS, invalid_signature) is None


def test_request_origin_parses_origin_referer_and_untrusted_or_malformed_values() -> None:
    assert _request_origin(make_request(origin="https://trusted.example/path")) == (
        "https://trusted.example"
    )
    assert _request_origin(make_request(origin=None, referer="https://trusted.example/page")) == (
        "https://trusted.example"
    )
    assert _request_origin(make_request(origin=None, referer=None)) is None
    assert _request_origin(make_request(origin="http://[malformed")) is None
    assert _request_origin(make_request(origin="https://user:secret@trusted.example")) is None
    assert _request_origin(make_request(origin="/relative")) is None
    assert _trusted_origin(make_request(origin="https://trusted.example/"))
    assert not _trusted_origin(make_request(origin="https://attacker.example"))


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS", "TRACE"])
async def test_safe_methods_do_not_require_origin_or_csrf(method: str) -> None:
    await enforce_csrf(make_request(method=method, origin=None))


@pytest.mark.asyncio
async def test_csrf_enforcement_rejects_bad_origin_missing_token_and_mismatch() -> None:
    token = issue_csrf_token(SETTINGS, SESSION_ID)
    with pytest.raises(ApiError) as untrusted:
        await enforce_csrf(make_request(origin=None))
    expect_code(untrusted, "CSRF_ORIGIN_INVALID")

    with pytest.raises(ApiError) as absent:
        await enforce_csrf(make_request())
    expect_code(absent, "CSRF_TOKEN_INVALID")

    with pytest.raises(ApiError) as mismatched:
        await enforce_csrf(
            make_request(
                cookies={"lab_csrf": token},
                csrf_header=issue_csrf_token(SETTINGS, SESSION_ID),
            )
        )
    expect_code(mismatched, "CSRF_TOKEN_INVALID")

    with pytest.raises(ApiError) as expired:
        await enforce_csrf(
            make_request(
                cookies={"lab_csrf": signed_token(int(time.time()) - 8 * 24 * 60 * 60)},
                csrf_header=signed_token(int(time.time()) - 8 * 24 * 60 * 60),
            )
        )
    expect_code(expired, "CSRF_TOKEN_INVALID")


@pytest.mark.asyncio
async def test_refresh_login_register_and_authenticated_routes_bind_csrf_to_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    csrf = issue_csrf_token(SETTINGS, SESSION_ID)
    refresh = f"{SESSION_ID}.{'r' * 43}"
    refresh_request = make_request(
        path="/api/v2/auth/refresh/",
        cookies={"lab_csrf": csrf, "lab_refresh": refresh},
        csrf_header=csrf,
    )
    await enforce_csrf(refresh_request)
    assert _csrf_session_id(refresh_request) == SESSION_ID

    bad_refresh_request = make_request(
        path="/api/v2/auth/refresh",
        cookies={"lab_csrf": csrf},
        csrf_header=csrf,
    )
    with pytest.raises(ApiError) as refresh_mismatch:
        await enforce_csrf(bad_refresh_request)
    expect_code(refresh_mismatch, "CSRF_SESSION_MISMATCH")

    for path in ("/api/v2/auth/login", "/api/v2/auth/register"):
        await enforce_csrf(
            make_request(path=path, cookies={"lab_csrf": csrf}, csrf_header=csrf)
        )

    def decode_access(_request, token: str, *, allow_expired: bool) -> str:
        assert allow_expired is True
        if token == "invalid":
            raise ApiError("AUTH_REQUIRED", "invalid", 401)
        return token

    monkeypatch.setattr(security, "decode_session_id", decode_access)
    authenticated = make_request(
        cookies={"lab_csrf": csrf, "lab_access": SESSION_ID},
        csrf_header=csrf,
    )
    await enforce_csrf(authenticated)
    assert _csrf_session_id(authenticated) == SESSION_ID

    bad_access = make_request(
        cookies={"lab_csrf": csrf, "lab_access": "invalid"},
        csrf_header=csrf,
    )
    with pytest.raises(ApiError) as access_mismatch:
        await enforce_csrf(bad_access)
    expect_code(access_mismatch, "CSRF_SESSION_MISMATCH")

    fallback_to_refresh = make_request(
        cookies={"lab_refresh": refresh},
    )
    assert _csrf_session_id(fallback_to_refresh) == SESSION_ID
