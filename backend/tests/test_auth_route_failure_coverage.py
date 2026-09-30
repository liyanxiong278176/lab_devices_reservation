from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.api.v2 import auth as auth_routes
from app.auth.sessions import SessionStoreUnavailable
from app.core.errors import ApiError
from app.core.settings import Settings
from app.infrastructure.db.models import Role
from app.main import create_app
from fastapi import Response
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request


class FakeSession:
    def __init__(self, *scalar_results: object, flush_error: Exception | None = None) -> None:
        self.scalar_results = list(scalar_results)
        self.flush_error = flush_error
        self.added: list[object] = []
        self.rolled_back = False

    async def scalar(self, _statement: object) -> object:
        if not self.scalar_results:
            raise AssertionError("unexpected scalar query")
        return self.scalar_results.pop(0)

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        if self.flush_error is not None:
            raise self.flush_error

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        self.rolled_back = True

    async def refresh(self, _value: object) -> None:
        return None


def _auth_app():
    app = create_app(Settings(environment="test", cors_origins=["http://test"]))
    app.state.notification_hub = SimpleNamespace(disconnect_session=AsyncMock())
    return app


def _request(app, *, refresh_token: str | None = None) -> Request:
    headers = []
    if refresh_token is not None:
        headers.append((b"cookie", f"lab_refresh={refresh_token}".encode()))
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.0"},
            "http_version": "1.1",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 1234),
            "scheme": "http",
            "method": "POST",
            "path": "/api/v2/auth/refresh",
            "raw_path": b"/api/v2/auth/refresh",
            "query_string": b"",
            "headers": headers,
            "app": app,
            "state": {},
        }
    )


@pytest.mark.asyncio
async def test_issue_session_retries_collisions_and_reports_store_failures(monkeypatch) -> None:
    app = _auth_app()
    request = _request(app)
    create_session = AsyncMock(side_effect=[False, True])
    monkeypatch.setattr(auth_routes, "create_session", create_session)
    monkeypatch.setattr(auth_routes, "create_access_token", lambda *_args, **_kwargs: "access")
    monkeypatch.setattr(auth_routes, "new_session_id", lambda: "session-id")
    monkeypatch.setattr(auth_routes, "new_refresh_token", lambda _sid: "refresh-token")

    issued = await auth_routes._issue_session(request, Response(), SimpleNamespace(id=4))
    assert issued.authenticated is True
    assert create_session.await_count == 2

    create_session.reset_mock(side_effect=True)
    create_session.side_effect = [False, False, False]
    with pytest.raises(ApiError) as collision_error:
        await auth_routes._issue_session(request, Response(), SimpleNamespace(id=4))
    assert collision_error.value.code == "AUTH_SESSION_CREATE_FAILED"
    assert create_session.await_count == 3

    create_session.side_effect = SessionStoreUnavailable("redis unavailable")
    with pytest.raises(ApiError) as unavailable_error:
        await auth_routes._issue_session(request, Response(), SimpleNamespace(id=4))
    assert unavailable_error.value.code == "AUTH_SESSION_UNAVAILABLE"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user", "password_valid", "code"),
    [
        (None, True, "INVALID_CREDENTIALS"),
        (
            SimpleNamespace(id=1, status=0, password_hash="hash", college_id=1, roles=[]),
            True,
            "INVALID_CREDENTIALS",
        ),
        (
            SimpleNamespace(id=1, status=1, password_hash="hash", college_id=1, roles=[]),
            False,
            "INVALID_CREDENTIALS",
        ),
        (
            SimpleNamespace(id=1, status=1, password_hash="hash", college_id=None, roles=[]),
            True,
            "COLLEGE_REQUIRED",
        ),
    ],
)
async def test_login_rejects_invalid_account_states(
    monkeypatch, user, password_valid, code
) -> None:
    app = _auth_app()
    monkeypatch.setattr(auth_routes, "enforce_login_rate_limit", AsyncMock())
    monkeypatch.setattr(auth_routes, "verify_password", lambda *_args: password_valid)
    with pytest.raises(ApiError) as error:
        await auth_routes.login(
            _request(app),
            Response(),
            auth_routes.LoginRequest(username=" person ", password="secret-pass"),
            FakeSession(user),
        )
    assert error.value.code == code


@pytest.mark.asyncio
async def test_registration_rejects_missing_college_or_student_role(monkeypatch) -> None:
    app = _auth_app()
    monkeypatch.setattr(auth_routes, "enforce_registration_rate_limit", AsyncMock())
    payload = auth_routes.RegisterRequest(
        username="new-user", password="StrongPass123!", real_name="新用户", college_id=1
    )

    with pytest.raises(ApiError) as college_error:
        await auth_routes.register(payload, _request(app), Response(), FakeSession(None))
    assert college_error.value.code == "COLLEGE_NOT_FOUND"

    with pytest.raises(ApiError) as role_error:
        await auth_routes.register(
            payload,
            _request(app),
            Response(),
            FakeSession(SimpleNamespace(id=1), None),
        )
    assert role_error.value.code == "ROLE_CONFIGURATION_MISSING"


@pytest.mark.asyncio
async def test_registration_rolls_back_unique_username_conflict(monkeypatch) -> None:
    app = _auth_app()
    session = FakeSession(
        SimpleNamespace(id=1),
        Role(role_code="STUDENT", role_name="学生"),
        flush_error=IntegrityError("INSERT", {}, RuntimeError("duplicate")),
    )
    monkeypatch.setattr(auth_routes, "enforce_registration_rate_limit", AsyncMock())

    with pytest.raises(ApiError) as error:
        await auth_routes.register(
            auth_routes.RegisterRequest(
                username="duplicate", password="StrongPass123!", real_name="重复用户", college_id=1
            ),
            _request(app),
            Response(),
            session,
        )
    assert error.value.code == "USERNAME_TAKEN"
    assert session.rolled_back is True


@pytest.mark.asyncio
@pytest.mark.parametrize("token", [None, "malformed"])
async def test_refresh_rejects_absent_or_malformed_cookie(monkeypatch, token) -> None:
    app = _auth_app()
    monkeypatch.setattr(
        auth_routes,
        "refresh_token_session_id",
        lambda value: "session-id" if value == "valid-refresh" else None,
    )
    with pytest.raises(ApiError) as error:
        await auth_routes.refresh(_request(app, refresh_token=token), Response(), FakeSession())
    assert error.value.code == "REFRESH_INVALID"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("current", "resolve_error", "expected_code"),
    [
        (None, None, "REFRESH_INVALID"),
        (None, SessionStoreUnavailable("redis unavailable"), "AUTH_SESSION_UNAVAILABLE"),
        (
            (SimpleNamespace(id=9, status=0), datetime.now(UTC) + timedelta(hours=1)),
            None,
            "USER_NOT_FOUND",
        ),
        (
            (SimpleNamespace(id=9, status=1), datetime.now(UTC) - timedelta(seconds=1)),
            None,
            "REFRESH_EXPIRED",
        ),
    ],
)
async def test_refresh_rejects_unavailable_missing_disabled_or_expired_session(
    monkeypatch, current, resolve_error, expected_code
) -> None:
    app = _auth_app()
    monkeypatch.setattr(auth_routes, "refresh_token_session_id", lambda _value: "session-id")
    resolve = (
        AsyncMock(side_effect=resolve_error)
        if resolve_error
        else AsyncMock(return_value=current)
    )
    delete = AsyncMock()
    monkeypatch.setattr(auth_routes, "resolve_refresh_session", resolve)
    monkeypatch.setattr(auth_routes, "delete_session", delete)

    with pytest.raises(ApiError) as error:
        await auth_routes.refresh(
            _request(app, refresh_token="valid-refresh"), Response(), FakeSession()
        )
    assert error.value.code == expected_code
    if expected_code in {"USER_NOT_FOUND", "REFRESH_EXPIRED"}:
        delete.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("rotate_result", "stored_user_id", "rotate_error", "expected_code"),
    [
        (None, None, SessionStoreUnavailable("redis unavailable"), "AUTH_SESSION_UNAVAILABLE"),
        (("reused", 9), 9, None, "REFRESH_REUSED"),
        (("rotated", 10), 10, None, "REFRESH_INVALID"),
    ],
)
async def test_refresh_handles_rotation_failure_replay_and_identity_mismatch(
    monkeypatch, rotate_result, stored_user_id, rotate_error, expected_code
) -> None:
    app = _auth_app()
    now = datetime.now(UTC)
    user = SimpleNamespace(id=9, status=1)
    monkeypatch.setattr(auth_routes, "refresh_token_session_id", lambda _value: "session-id")
    monkeypatch.setattr(
        auth_routes,
        "resolve_refresh_session",
        AsyncMock(return_value=(user, now + timedelta(hours=1))),
    )
    rotate = AsyncMock(side_effect=rotate_error) if rotate_error else AsyncMock(
        return_value=rotate_result
    )
    monkeypatch.setattr(auth_routes, "rotate_refresh_token", rotate)

    with pytest.raises(ApiError) as error:
        await auth_routes.refresh(
            _request(app, refresh_token="valid-refresh"), Response(), FakeSession()
        )
    assert error.value.code == expected_code
    if expected_code == "REFRESH_REUSED":
        app.state.notification_hub.disconnect_session.assert_awaited_once_with("session-id")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stored_session",
    [None, {}, {"user_id": "not-an-integer", "expires_at": "2026-10-01T00:00:00+00:00"}],
)
async def test_resolve_refresh_session_handles_missing_or_malformed_store_data(
    monkeypatch, stored_session
) -> None:
    import app.auth.sessions as sessions

    monkeypatch.setattr(sessions, "get_session", AsyncMock(return_value=stored_session))
    if stored_session is None:
        result = await auth_routes.resolve_refresh_session(
            _request(_auth_app()), "session-id", FakeSession()
        )
        assert result is None
    else:
        with pytest.raises(ApiError) as error:
            await auth_routes.resolve_refresh_session(
                _request(_auth_app()), "session-id", FakeSession()
            )
        assert error.value.code == "AUTH_SESSION_INVALID"


@pytest.mark.asyncio
async def test_resolve_refresh_session_handles_deleted_and_active_users(monkeypatch) -> None:
    import app.auth.sessions as sessions

    monkeypatch.setattr(
        sessions,
        "get_session",
        AsyncMock(
            return_value={
                "user_id": "123",
                "expires_at": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
            }
        ),
    )
    assert (
        await auth_routes.resolve_refresh_session(
            _request(_auth_app()), "session-id", FakeSession(None)
        )
        is None
    )

    user = SimpleNamespace(id=123)
    resolved = await auth_routes.resolve_refresh_session(
        _request(_auth_app()), "session-id", FakeSession(user)
    )
    assert resolved is not None and resolved[0] is user
    assert resolved[1].tzinfo is UTC


@pytest.mark.asyncio
async def test_logout_returns_unavailable_when_revocation_fails(monkeypatch) -> None:
    app = _auth_app()
    monkeypatch.setattr(
        auth_routes,
        "delete_session",
        AsyncMock(side_effect=SessionStoreUnavailable("redis unavailable")),
    )
    principal = SimpleNamespace(session_id="session-id", user_id=9)
    with pytest.raises(ApiError) as error:
        await auth_routes.logout(_request(app), Response(), principal)
    assert error.value.code == "AUTH_SESSION_UNAVAILABLE"
