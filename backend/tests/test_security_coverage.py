from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import app.auth.security as security
import jwt
import pytest
from app.auth.rbac import AuthorizationSnapshot
from app.auth.sessions import SessionStoreUnavailable
from app.core.errors import ApiError
from app.core.settings import Settings

SESSION_ID = "s" * 43


def make_request(*, cookies: dict[str, str] | None = None) -> SimpleNamespace:
    settings = Settings(environment="test", _env_file=None)
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=settings)),
        cookies=cookies or {},
    )


def access_token(
    request: SimpleNamespace,
    *,
    sid: str = SESSION_ID,
    token_type: str = "access",
) -> str:
    settings = request.app.state.settings
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sid": sid,
            "type": token_type,
            "jti": "token-id",
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )


def make_principal(**overrides: object) -> security.Principal:
    values: dict[str, object] = {
        "user_id": 4,
        "username": "person",
        "college_id": 9,
        "roles": ("STUDENT",),
        "token_type": "access",
        "token_id": "jti",
        "permissions": ("device:read",),
        "session_id": SESSION_ID,
    }
    values.update(overrides)
    return security.Principal(**values)  # type: ignore[arg-type]


def assert_api_code(error: pytest.ExceptionInfo[ApiError], code: str) -> None:
    assert error.value.code == code


def test_principal_roles_permission_and_college_scope_branches() -> None:
    student = make_principal()
    assert not student.is_system_admin
    assert not student.is_lab_admin
    assert student.has_permission("device:read")
    assert not student.has_permission("user:manage")
    assert security.college_scope(student) == 9

    manager = make_principal(roles=("LAB_ADMIN",))
    assert manager.is_lab_admin
    admin = make_principal(roles=("SYS_ADMIN",), college_id=None)
    assert admin.is_system_admin
    assert admin.is_lab_admin
    assert admin.has_permission("anything")
    assert security.college_scope(admin) is None

    with pytest.raises(ApiError) as missing_scope:
        security.college_scope(make_principal(college_id=None))
    assert_api_code(missing_scope, "COLLEGE_SCOPE_MISSING")


def test_password_verification_accepts_valid_hash_and_rejects_bad_hashes() -> None:
    hashed = security.hash_password("strong-password")
    assert security.verify_password("strong-password", hashed)
    assert not security.verify_password("wrong-password", hashed)
    assert not security.verify_password("password", "not-a-supported-hash")
    assert not security.verify_password("password", None)  # type: ignore[arg-type]


def test_access_token_round_trip_and_rejects_invalid_claims() -> None:
    request = make_request()
    token = security.create_access_token(request, session_id=SESSION_ID)
    assert security.decode_session_id(request, token) == SESSION_ID
    assert security.decode_session_id(request, token, allow_expired=True) == SESSION_ID

    wrong_type = access_token(request, token_type="refresh")
    with pytest.raises(ApiError) as token_type_error:
        security.decode_session_id(request, wrong_type)
    assert_api_code(token_type_error, "TOKEN_TYPE_INVALID")

    short_session = access_token(request, sid="too-short")
    with pytest.raises(ApiError) as short_error:
        security.decode_session_id(request, short_session)
    assert_api_code(short_error, "TOKEN_INVALID")

    expired = jwt.encode(
        {
            "sid": SESSION_ID,
            "type": "access",
            "jti": "expired",
            "iss": request.app.state.settings.jwt_issuer,
            "aud": request.app.state.settings.jwt_audience,
            "iat": datetime.now(UTC) - timedelta(hours=2),
            "exp": datetime.now(UTC) - timedelta(hours=1),
        },
        request.app.state.settings.jwt_secret,
        algorithm="HS256",
    )
    with pytest.raises(ApiError) as expired_error:
        security.decode_session_id(request, expired)
    assert_api_code(expired_error, "TOKEN_INVALID")

    with pytest.raises(ApiError) as malformed:
        security.decode_session_id(request, "not-a-jwt")
    assert_api_code(malformed, "TOKEN_INVALID")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("redis_session", "exception", "code"),
    [
        (None, None, "AUTH_SESSION_INVALID"),
        (None, SessionStoreUnavailable("redis offline"), "AUTH_SESSION_UNAVAILABLE"),
        ({"user_id": "bad", "expires_at": "1"}, None, "AUTH_SESSION_INVALID"),
    ],
)
async def test_resolve_principal_rejects_missing_unavailable_and_corrupt_sessions(
    monkeypatch: pytest.MonkeyPatch,
    redis_session: dict[str, str] | None,
    exception: Exception | None,
    code: str,
) -> None:
    request = make_request()
    if exception is None:
        monkeypatch.setattr(security, "get_session", AsyncMock(return_value=redis_session))
    else:
        monkeypatch.setattr(security, "get_session", AsyncMock(side_effect=exception))
    with pytest.raises(ApiError) as error:
        await security.resolve_principal(request, access_token(request), AsyncMock())
    assert_api_code(error, code)


@pytest.mark.asyncio
async def test_resolve_principal_uses_current_account_state_and_authorization_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = make_request()
    redis_data = {"user_id": "4", "expires_at": "2000000000"}
    monkeypatch.setattr(security, "get_session", AsyncMock(return_value=redis_data))
    session = SimpleNamespace(scalar=AsyncMock(return_value=None))
    with pytest.raises(ApiError) as disabled:
        await security.resolve_principal(request, access_token(request), session)
    assert_api_code(disabled, "USER_NOT_FOUND")

    user = SimpleNamespace(id=4, username="person", college_id=9)
    session.scalar = AsyncMock(return_value=user)
    snapshot = AuthorizationSnapshot(3, ("STUDENT",), ("device:read", "reservation:create"))
    monkeypatch.setattr(security, "get_authorization_snapshot", AsyncMock(return_value=snapshot))
    resolved = await security.resolve_principal(request, access_token(request), session)
    assert resolved.user_id == user.id
    assert resolved.username == user.username
    assert resolved.college_id == user.college_id
    assert resolved.roles == snapshot.roles
    assert resolved.permissions == snapshot.permissions
    assert resolved.session_id == SESSION_ID


@pytest.mark.asyncio
async def test_current_user_and_principal_dependencies_enforce_enabled_account_and_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = make_request()
    with pytest.raises(ApiError) as no_cookie:
        await security.get_current_principal(request, AsyncMock())
    assert_api_code(no_cookie, "AUTH_REQUIRED")

    token = access_token(request)
    request.cookies = {request.app.state.settings.access_cookie_name: token}
    principal = make_principal()
    monkeypatch.setattr(security, "resolve_principal", AsyncMock(return_value=principal))
    assert await security.get_current_principal(request, AsyncMock()) is principal

    session = SimpleNamespace(scalar=AsyncMock(return_value=None))
    with pytest.raises(ApiError) as disabled:
        await security.get_current_user(principal, session)
    assert_api_code(disabled, "USER_NOT_FOUND")
    user = SimpleNamespace(id=principal.user_id, status=1)
    session.scalar = AsyncMock(return_value=user)
    assert await security.get_current_user(principal, session) is user


@pytest.mark.asyncio
async def test_permission_and_role_dependencies_allow_and_deny_as_expected() -> None:
    principal = make_principal()
    permission_gate = security.require_permissions("device:read", "reservation:create")
    with pytest.raises(ApiError) as denied:
        await permission_gate(principal)
    assert_api_code(denied, "FORBIDDEN")
    assert await security.require_permissions("device:read")(principal) is principal

    role_gate = security.require_roles("LAB_ADMIN")
    with pytest.raises(ApiError) as role_denied:
        await role_gate(principal)
    assert_api_code(role_denied, "FORBIDDEN")
    manager = make_principal(roles=("LAB_ADMIN",))
    assert await role_gate(manager) is manager
    admin = make_principal(roles=("SYS_ADMIN",))
    assert await role_gate(admin) is admin
