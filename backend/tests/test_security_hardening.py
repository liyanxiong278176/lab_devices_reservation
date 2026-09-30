from __future__ import annotations

import pytest
from app.auth.security import Principal
from app.core.client_ip import resolve_client_ip
from app.core.errors import ApiError
from app.core.settings import Settings
from app.infrastructure.cache.rate_limit import enforce_registration_rate_limit
from app.infrastructure.db.models import Role, User
from app.infrastructure.db.session import get_db
from app.main import create_app
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from starlette.requests import Request


def _request(app: FastAPI, path: str) -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.0"},
            "http_version": "1.1",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 1234),
            "scheme": "http",
            "method": "POST",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "app": app,
            "state": {},
        }
    )


def test_forwarded_for_is_ignored_without_trusted_proxy() -> None:
    assert resolve_client_ip("203.0.113.10", "198.51.100.7") == "203.0.113.10"


def test_forwarded_for_walks_back_to_nearest_untrusted_hop() -> None:
    assert resolve_client_ip("10.0.0.2", "198.51.100.8, 10.0.0.1", ["10.0.0.0/8"]) == "198.51.100.8"


def test_invalid_forwarded_chain_fails_closed_to_peer() -> None:
    assert resolve_client_ip("10.0.0.2", "198.51.100.8, not-an-ip", ["10.0.0.0/8"]) == "10.0.0.2"


def test_production_settings_reject_mysql_root_runtime_account() -> None:
    with pytest.raises(ValidationError, match="非 root 数据库账号"):
        Settings(
            environment="prod",
            jwt_secret="s" * 48,
            cookie_secure=True,
            mysql_dsn="mysql+asyncmy://root:separate-strong-value@localhost/lab_reservation",
        )


def test_production_settings_reject_public_jwt_example_placeholder() -> None:
    with pytest.raises(ValidationError, match="LAB_JWT_SECRET"):
        Settings(
            environment="prod",
            jwt_secret="replace-with-a-long-random-secret-at-least-32-characters",
            cookie_secure=True,
        )


@pytest.mark.asyncio
async def test_public_registration_rate_limit_uses_local_fallback() -> None:
    app = FastAPI()
    app.state.settings = Settings(
        environment="test",
        rate_limit_enabled=True,
        rate_limit_register_ip_capacity=1,
        rate_limit_register_ip_refill_per_second=0.001,
        rate_limit_register_username_capacity=10,
        rate_limit_register_username_refill_per_second=1,
    )

    class DownRedis:
        async def eval(self, *_args):
            raise ConnectionError("redis unavailable")

    app.state.redis_client = DownRedis()
    await enforce_registration_rate_limit(_request(app, "/api/v2/auth/register"), "public-user-one")
    with pytest.raises(ApiError) as error:
        await enforce_registration_rate_limit(
            _request(app, "/api/v2/auth/register"), "public-user-two"
        )
    assert error.value.status_code == 429
    assert error.value.data["source"] == "local"


@pytest.mark.asyncio
async def test_registration_selects_college_and_authenticates_immediately(seeded) -> None:
    factory, college, other_college, _, _, _, _, _ = seeded
    app = create_app(
        Settings(
            environment="test",
            cors_origins=["http://test"],
            redis_url="redis://127.0.0.1:6379/15",
            enable_workers=False,
            rate_limit_enabled=False,
        )
    )

    async def override_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            csrf_response = await client.get("/api/v2/auth/csrf")
            csrf = {
                "Origin": "http://test",
                "X-CSRF-Token": csrf_response.json()["data"]["csrf_token"],
            }
            colleges = await client.get("/api/v2/auth/colleges")
            assert {row["id"] for row in colleges.json()["data"]} == {college.id, other_college.id}
            registered = await client.post(
                "/api/v2/auth/register",
                json={
                    "username": "registered-student",
                    "password": "Password123!",
                    "real_name": "新注册学生",
                    "college_id": college.id,
                },
                headers=csrf,
            )
            assert registered.status_code == 201
            payload = registered.json()
            assert payload["code"] == "OK"
            assert payload["data"]["authenticated"] is True
            csrf["X-CSRF-Token"] = payload["data"]["csrf_token"]
            assert client.cookies.get("lab_access")
            assert client.cookies.get("lab_refresh")

            me = await client.get("/api/v2/auth/me")
            assert me.status_code == 200
            assert me.json()["data"]["college_id"] == college.id
            assert me.json()["data"]["roles"] == ["STUDENT"]

            duplicate = await client.post(
                "/api/v2/auth/register",
                json={
                    "username": "registered-student",
                    "password": "DifferentPassword123!",
                    "real_name": "重复注册",
                    "college_id": college.id,
                },
                headers=csrf,
            )
            assert duplicate.status_code == 409
            login = await client.post(
                "/api/v2/auth/login",
                json={"username": "registered-student", "password": "Password123!"},
                headers=csrf,
            )
            assert login.status_code == 200

        async with factory() as session:
            created_user = await session.scalar(
                select(User)
                .options(selectinload(User.roles))
                .where(User.username == "registered-student")
            )
            assert created_user is not None
            assert created_user.status == 1
            assert created_user.college_id == college.id
            assert [role.role_code for role in created_user.roles] == ["STUDENT"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_admin_cannot_enable_unassigned_regular_user(seeded) -> None:
    factory, _, _, _, _, manager, _, _ = seeded
    from app.api.v2.users import update_user_status

    async with factory() as session:
        pending = User(
            username="unassigned-pending",
            password_hash="unused",
            real_name="待分配",
            status=0,
            college_id=None,
        )
        student_role = await session.scalar(select(Role).where(Role.role_code == "STUDENT"))
        if student_role is not None:
            pending.roles.append(student_role)
        session.add(pending)
        await session.commit()
        pending_id = pending.id

        admin = Principal(
            user_id=manager.id,
            username=manager.username,
            college_id=manager.college_id,
            roles=("SYS_ADMIN",),
            token_type="access",
            token_id="registration-review-test",
        )
        with pytest.raises(ApiError) as error:
            await update_user_status(
                pending_id,
                _request(FastAPI(), "/api/v2/users/1/status"),
                1,
                admin,
                session,
            )
        assert error.value.code == "COLLEGE_REQUIRED"
