from __future__ import annotations

import pytest
from app.auth.security import hash_password
from app.core.settings import Settings
from app.infrastructure.db.models import RefreshSession, User
from app.infrastructure.db.session import get_db
from app.main import create_app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select


async def _client_for(factory, *, settings: Settings):
    app = create_app(settings)

    async def override_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    return app, AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_logout_revokes_access_and_refresh_tokens_for_the_session_family(seeded) -> None:
    factory, _, _, user, *_ = seeded
    async with factory() as session:
        persisted_user = await session.get(User, user.id)
        assert persisted_user is not None
        persisted_user.password_hash = hash_password("StrongPassword123!")
        await session.commit()

    app, client = await _client_for(
        factory,
        settings=Settings(environment="test", cors_origins=[], rate_limit_enabled=False),
    )
    async with client:
        login = await client.post(
            "/api/v2/auth/login",
            json={"username": user.username, "password": "StrongPassword123!"},
        )
        tokens = login.json()["data"]
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        assert (await client.get("/api/v2/auth/me", headers=headers)).status_code == 200
        assert (await client.get("/api/v2/ready", headers=headers)).status_code == 403

        logout = await client.post(
            "/api/v2/auth/logout",
            json={"refresh_token": tokens["refresh_token"]},
        )
        assert logout.status_code == 200
        assert (await client.get("/api/v2/auth/me", headers=headers)).status_code == 401
        assert (
            await client.post(
                "/api/v2/auth/refresh",
                json={"refresh_token": tokens["refresh_token"]},
            )
        ).status_code == 401
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_replayed_rotated_refresh_token_revokes_the_entire_family(seeded) -> None:
    factory, _, _, user, *_ = seeded
    async with factory() as session:
        persisted_user = await session.get(User, user.id)
        assert persisted_user is not None
        persisted_user.password_hash = hash_password("StrongPassword123!")
        await session.commit()

    app, client = await _client_for(
        factory,
        settings=Settings(environment="test", cors_origins=[], rate_limit_enabled=False),
    )
    async with client:
        login = await client.post(
            "/api/v2/auth/login",
            json={"username": user.username, "password": "StrongPassword123!"},
        )
        first = login.json()["data"]
        rotated_response = await client.post(
            "/api/v2/auth/refresh",
            json={"refresh_token": first["refresh_token"]},
        )
        assert rotated_response.status_code == 200
        rotated = rotated_response.json()["data"]
        assert (
            await client.get(
                "/api/v2/auth/me",
                headers={"Authorization": f"Bearer {first['access_token']}"},
            )
        ).status_code == 200

        replay = await client.post(
            "/api/v2/auth/refresh",
            json={"refresh_token": first["refresh_token"]},
        )
        assert replay.status_code == 401
        assert replay.json()["code"] == "REFRESH_REUSED"

        for access_token in (first["access_token"], rotated["access_token"]):
            response = await client.get(
                "/api/v2/auth/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            assert response.status_code == 401
        assert (
            await client.post(
                "/api/v2/auth/refresh",
                json={"refresh_token": rotated["refresh_token"]},
            )
        ).status_code == 401

        async with factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(RefreshSession).where(RefreshSession.user_id == user.id)
                    )
                ).all()
            )
        assert len(rows) == 2
        assert all(row.revoked_at is not None for row in rows)
    app.dependency_overrides.clear()
