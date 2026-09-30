from __future__ import annotations

import jwt
import pytest
from app.auth.rbac import bump_authz_version
from app.auth.security import hash_password
from app.core.settings import Settings
from app.infrastructure.db.models import Permission, RefreshSession, Role, User
from app.infrastructure.db.session import get_db
from app.main import create_app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import selectinload


async def _client_for(factory, *, settings: Settings):
    app = create_app(settings)

    async def override_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    return app, AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _csrf(client: AsyncClient) -> dict[str, str]:
    response = await client.get("/api/v2/auth/csrf")
    assert response.status_code == 200
    return {
        "Origin": "http://test",
        "X-CSRF-Token": response.json()["data"]["csrf_token"],
    }


def _test_settings() -> Settings:
    return Settings(
        environment="test",
        cors_origins=["http://test"],
        redis_url="redis://127.0.0.1:6379/15",
        rate_limit_enabled=False,
    )


@pytest.mark.asyncio
async def test_cookie_session_login_refresh_rotation_and_logout(seeded) -> None:
    factory, _, _, user, *_ = seeded
    async with factory() as session:
        persisted_user = await session.get(User, user.id)
        assert persisted_user is not None
        persisted_user.password_hash = hash_password("StrongPassword123!")
        await session.commit()

    app, client = await _client_for(factory, settings=_test_settings())
    async with client:
        csrf = await _csrf(client)
        initial_csrf_token = csrf["X-CSRF-Token"]
        # Multiple tabs initialize the same cookie session. Re-reading the
        # endpoint must not invalidate a token another tab already holds.
        repeated_csrf = await client.get("/api/v2/auth/csrf")
        assert repeated_csrf.json()["data"]["csrf_token"] == initial_csrf_token
        login = await client.post(
            "/api/v2/auth/login",
            json={"username": user.username, "password": "StrongPassword123!"},
            headers=csrf,
        )
        assert login.status_code == 200
        session_data = login.json()["data"]
        assert set(session_data) == {"authenticated", "expires_in", "csrf_token"}
        assert session_data["authenticated"] is True
        csrf["X-CSRF-Token"] = session_data["csrf_token"]

        access = client.cookies.get("lab_access")
        refresh = client.cookies.get("lab_refresh")
        assert access and refresh and "." in refresh
        claims = jwt.decode(
            access,
            _test_settings().jwt_secret,
            algorithms=["HS256"],
            audience="lab-reservation-web",
            issuer="lab-reservation",
        )
        assert set(claims) == {"sid", "type", "jti", "iss", "aud", "iat", "exp"}
        me = await client.get("/api/v2/auth/me")
        assert me.status_code == 200
        assert me.json()["data"]["id"] == user.id
        assert "reservation:create" in me.json()["data"]["permissions"]
        assert (await client.get("/api/v2/ready")).status_code == 403

        rotated_response = await client.post("/api/v2/auth/refresh", json={}, headers=csrf)
        assert rotated_response.status_code == 200
        rotated = rotated_response.json()["data"]
        assert rotated["csrf_token"]
        assert rotated["csrf_token"] == session_data["csrf_token"]
        assert client.cookies.get("lab_refresh") != refresh
        csrf["X-CSRF-Token"] = rotated["csrf_token"]

        logout = await client.post("/api/v2/auth/logout", json={}, headers=csrf)
        assert logout.status_code == 200
        assert (await client.get("/api/v2/auth/me")).status_code == 401
        assert client.cookies.get("lab_access") is None
        assert client.cookies.get("lab_refresh") is None

    async with factory() as session:
        legacy_rows = list((await session.scalars(select(RefreshSession))).all())
        assert legacy_rows == []
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_replayed_refresh_cookie_revokes_the_session(seeded) -> None:
    factory, _, _, user, *_ = seeded
    async with factory() as session:
        persisted_user = await session.get(User, user.id)
        assert persisted_user is not None
        persisted_user.password_hash = hash_password("StrongPassword123!")
        await session.commit()

    app, client = await _client_for(factory, settings=_test_settings())
    async with client:
        csrf = await _csrf(client)
        login = await client.post(
            "/api/v2/auth/login",
            json={"username": user.username, "password": "StrongPassword123!"},
            headers=csrf,
        )
        assert login.status_code == 200
        original_refresh = client.cookies.get("lab_refresh")
        csrf["X-CSRF-Token"] = login.json()["data"]["csrf_token"]
        rotated = await client.post("/api/v2/auth/refresh", json={}, headers=csrf)
        assert rotated.status_code == 200
        csrf["X-CSRF-Token"] = rotated.json()["data"]["csrf_token"]

        replay = await client.post(
            "/api/v2/auth/refresh",
            json={},
            headers={
                **csrf,
                "Cookie": f"lab_refresh={original_refresh}; lab_csrf={csrf['X-CSRF-Token']}",
            },
        )
        assert replay.status_code == 401
        assert replay.json()["code"] == "REFRESH_REUSED"
        assert (await client.get("/api/v2/auth/me")).status_code == 401
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_role_permission_change_invalidates_cached_session_snapshot(seeded) -> None:
    factory, _, _, user, *_ = seeded
    async with factory() as session:
        persisted_user = await session.get(User, user.id)
        assert persisted_user is not None
        persisted_user.password_hash = hash_password("StrongPassword123!")
        await session.commit()

    app, client = await _client_for(factory, settings=_test_settings())
    async with client:
        csrf = await _csrf(client)
        login = await client.post(
            "/api/v2/auth/login",
            json={"username": user.username, "password": "StrongPassword123!"},
            headers=csrf,
        )
        assert login.status_code == 200
        csrf["X-CSRF-Token"] = login.json()["data"]["csrf_token"]
        initial = await client.get("/api/v2/auth/me")
        assert "reservation:create" in initial.json()["data"]["permissions"]

        async with factory() as session:
            role = await session.scalar(
                select(Role)
                .options(selectinload(Role.permissions))
                .where(Role.role_code == "STUDENT")
            )
            added_permission = await session.scalar(
                select(Permission).where(Permission.permission_code == "organization:read")
            )
            assert role is not None and added_permission is not None
            role.permissions = [
                permission
                for permission in role.permissions
                if permission.permission_code != "reservation:create"
            ] + [added_permission]
            await bump_authz_version(session)
            await session.commit()

        changed = await client.get("/api/v2/auth/me")
        assert changed.status_code == 200
        current_permissions = set(changed.json()["data"]["permissions"])
        assert "reservation:create" not in current_permissions
        assert "organization:read" in current_permissions

        logout = await client.post("/api/v2/auth/logout", json={}, headers=csrf)
        assert logout.status_code == 200
    app.dependency_overrides.clear()
