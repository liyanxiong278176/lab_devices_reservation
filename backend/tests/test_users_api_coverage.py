from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from app.auth.csrf import enforce_csrf
from app.auth.security import Principal, get_current_principal
from app.auth.sessions import SessionStoreUnavailable
from app.core.settings import Settings
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.db.models import AuthorizationVersion, College, Role, User
from app.infrastructure.db.session import get_db
from app.main import create_app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload


def _admin(user_id: int, username: str = "api-admin", college_id: int | None = 1) -> Principal:
    return Principal(
        user_id=user_id,
        username=username,
        college_id=college_id,
        roles=("SYS_ADMIN",),
        token_type="access",
        token_id=f"users-api-test-{user_id}",
        permissions=("user:manage",),
    )


@asynccontextmanager
async def _client(
    session_factory: async_sessionmaker[AsyncSession],
    actor: dict[str, Principal],
    *,
    raise_app_exceptions: bool = True,
) -> AsyncIterator[AsyncClient]:
    app = create_app(
        Settings(
            environment="test",
            mysql_dsn="sqlite+aiosqlite:///:memory:",
            cors_origins=["http://test"],
            redis_url="redis://127.0.0.1:6379/15",
            rate_limit_enabled=False,
        )
    )

    async def override_db():
        async with session_factory() as session:
            yield session

    async def override_actor() -> Principal:
        return actor["value"]

    async def no_csrf() -> None:
        return None

    async def no_rate_limit() -> None:
        return None

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_principal] = override_actor
    app.dependency_overrides[enforce_csrf] = no_csrf
    app.dependency_overrides[enforce_authenticated_rate_limit] = no_rate_limit
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions),
            base_url="http://test",
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def _body(username: str, college_id: int | None, **updates: object) -> dict[str, object]:
    result: dict[str, object] = {
        "username": username,
        "password": "valid-password-123",
        "real_name": "测试账号",
        "phone": "13800000000",
        "email": "test@example.org",
        "user_type": "STUDENT",
        "role_codes": ["STUDENT"],
        "college_id": college_id,
    }
    result.update(updates)
    return result


@pytest.mark.asyncio
async def test_admin_lists_creates_and_validates_users(seeded) -> None:
    factory, college, _other_college, student, _other_student, manager, *_ = seeded
    actor = {"value": _admin(manager.id, manager.username, college.id)}
    async with _client(factory, actor) as client:
        created = await client.post("/api/v2/users", json=_body("new-campus-user", college.id))
        assert created.status_code == 201
        user = created.json()["data"]
        assert user["username"] == "new-campus-user"
        assert user["roles"] == ["STUDENT"]
        new_user_id = user["id"]

        listed = await client.get(
            "/api/v2/users?username=campus&real_name=%E6%B5%8B%E8%AF%95&status=1&page=1&size=5"
        )
        assert listed.status_code == 200
        assert [row["id"] for row in listed.json()["data"]["records"]] == [new_user_id]
        unfiltered = await client.get("/api/v2/users")
        assert unfiltered.status_code == 200
        assert unfiltered.json()["data"]["total"] >= 4

        duplicate = await client.post("/api/v2/users", json=_body(student.username, college.id))
        assert duplicate.status_code == 409

        no_password = await client.post(
            "/api/v2/users", json=_body("password-missing-user", college.id, password=None)
        )
        assert no_password.status_code == 422

        duplicate_roles = await client.post(
            "/api/v2/users",
            json=_body("duplicate-role-user", college.id, role_codes=["STUDENT", "STUDENT"]),
        )
        assert duplicate_roles.status_code == 422
        assert duplicate_roles.json()["code"] == "DUPLICATE_ROLE"

        missing_role = await client.post(
            "/api/v2/users",
            json=_body("missing-role-user", college.id, role_codes=["NO_SUCH_ROLE"]),
        )
        assert missing_role.status_code == 422
        assert missing_role.json()["code"] == "ROLE_NOT_FOUND"

        invalid_college = await client.post(
            "/api/v2/users", json=_body("invalid-college-user", 999999)
        )
        assert invalid_college.status_code == 422

        blank_username = await client.post("/api/v2/users", json=_body("   ", college.id))
        assert blank_username.status_code == 422

    async with _client(factory, actor, raise_app_exceptions=False) as client:
        duplicate_after_normalization = await client.post(
            "/api/v2/users", json=_body(f"  {student.username}  ", college.id)
        )
    assert duplicate_after_normalization.status_code == 409

    actor["value"] = Principal(
        user_id=student.id,
        username=student.username,
        college_id=college.id,
        roles=("STUDENT",),
        token_type="access",
        token_id="normal-user",
        permissions=("user:manage",),
    )
    async with _client(factory, actor) as client:
        forbidden = await client.get("/api/v2/users")
    assert forbidden.status_code == 403


@pytest.mark.asyncio
async def test_user_update_rotates_authorization_and_requires_session_store(
    seeded, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v2 import users as users_api

    factory, college, _other_college, student, _other_student, manager, *_ = seeded
    actor = {"value": _admin(manager.id, manager.username, college.id)}

    async def revoke_success(_request: object, _user_id: int) -> None:
        return None

    monkeypatch.setattr(users_api, "revoke_user_sessions", revoke_success)
    async with _client(factory, actor) as client:
        updated = await client.put(
            f"/api/v2/users/{student.id}",
            json=_body(
                student.username,
                college.id,
                password=None,
                role_codes=["LAB_ADMIN"],
                real_name="提升权限后更新",
            ),
        )
        assert updated.status_code == 200
        assert updated.json()["data"]["roles"] == ["LAB_ADMIN"]
        assert updated.json()["data"]["real_name"] == "提升权限后更新"

        async with factory() as session:
            version = await session.get(AuthorizationVersion, 1)
            assert version is not None and version.version == 2

        password_updated = await client.put(
            f"/api/v2/users/{student.id}",
            json=_body(
                student.username,
                college.id,
                password="rotated-password-456",
                role_codes=["LAB_ADMIN"],
            ),
        )
        assert password_updated.status_code == 200

        missing = await client.put("/api/v2/users/999999", json=_body("unused-user", college.id))
        assert missing.status_code == 404

        async def revoke_unavailable(_request: object, _user_id: int) -> None:
            raise SessionStoreUnavailable("redis unavailable")

        monkeypatch.setattr(users_api, "revoke_user_sessions", revoke_unavailable)
        rejected = await client.put(
            f"/api/v2/users/{student.id}",
            json=_body(
                student.username,
                college.id,
                password="must-not-commit-789",
                real_name="不应落库",
                role_codes=["LAB_ADMIN"],
            ),
        )
        assert rejected.status_code == 503
        assert rejected.json()["code"] == "AUTH_SESSION_UNAVAILABLE"

    async with factory() as session:
        stored = await session.get(User, student.id)
        assert stored is not None
        assert stored.real_name == "测试账号" or stored.real_name == "学生一"


@pytest.mark.asyncio
async def test_user_disable_delete_last_admin_guards_and_unavailable_redis_fallback(
    seeded, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v2 import users as users_api

    factory, college, _other_college, student, other_student, manager, *_ = seeded
    async with factory() as session:
        admin_role = await session.scalar(select(Role).where(Role.role_code == "SYS_ADMIN"))
        assert admin_role is not None
        target_admin = await session.scalar(
            select(User).options(selectinload(User.roles)).where(User.id == student.id)
        )
        assert target_admin is not None
        target_admin.roles.append(admin_role)
        unassigned = User(
            username="unassigned-campus-user",
            password_hash="hash",
            college_id=None,
            status=0,
        )
        session.add(unassigned)
        await session.commit()
        unassigned_id = unassigned.id

    async def revoke_unavailable(_request: object, _user_id: int) -> None:
        raise SessionStoreUnavailable("redis unavailable")

    monkeypatch.setattr(users_api, "revoke_user_sessions", revoke_unavailable)
    actor = {"value": _admin(manager.id, manager.username, college.id)}
    async with _client(factory, actor) as client:
        last_admin_status = await client.patch(f"/api/v2/users/{student.id}/status?status=0")
        assert last_admin_status.status_code == 409
        assert last_admin_status.json()["code"] == "LAST_SYSTEM_ADMIN"

        last_admin_delete = await client.delete(f"/api/v2/users/{student.id}")
        assert last_admin_delete.status_code == 409
        assert last_admin_delete.json()["code"] == "LAST_SYSTEM_ADMIN"

        remove_admin_role = await client.put(
            f"/api/v2/users/{student.id}",
            json=_body(student.username, college.id, role_codes=["STUDENT"]),
        )
        assert remove_admin_role.status_code == 409
        assert remove_admin_role.json()["code"] == "LAST_SYSTEM_ADMIN"

        async with factory() as session:
            active_manager = await session.scalar(
                select(User).options(selectinload(User.roles)).where(User.id == manager.id)
            )
            second_admin_role = await session.scalar(
                select(Role).where(Role.role_code == "SYS_ADMIN")
            )
            assert active_manager is not None and second_admin_role is not None
            active_manager.roles.append(second_admin_role)
            await session.commit()

        one_of_two_admins = await client.patch(f"/api/v2/users/{student.id}/status?status=0")
        assert one_of_two_admins.status_code == 200

        self_delete = await client.delete(f"/api/v2/users/{manager.id}")
        assert self_delete.status_code == 409
        assert self_delete.json()["code"] == "SELF_DELETE_FORBIDDEN"

        self_disable = await client.patch(f"/api/v2/users/{manager.id}/status?status=0")
        assert self_disable.status_code == 409
        assert self_disable.json()["code"] == "SELF_DISABLE_FORBIDDEN"

        no_college = await client.patch(f"/api/v2/users/{unassigned_id}/status?status=1")
        assert no_college.status_code == 422
        assert no_college.json()["code"] == "COLLEGE_REQUIRED"

        disabled = await client.patch(f"/api/v2/users/{other_student.id}/status?status=0")
        assert disabled.status_code == 200
        enabled = await client.patch(f"/api/v2/users/{other_student.id}/status?status=1")
        assert enabled.status_code == 200

        unavailable_session_delete = await client.delete(f"/api/v2/users/{other_student.id}")
        assert unavailable_session_delete.status_code == 200

        missing_delete = await client.delete("/api/v2/users/999999")
        assert missing_delete.status_code == 404
        missing_status = await client.patch("/api/v2/users/999999/status?status=0")
        assert missing_status.status_code == 404

    async with factory() as session:
        disabled = await session.get(User, other_student.id)
        assert disabled is not None and disabled.status == 0


@pytest.mark.asyncio
async def test_create_requires_tenant_unless_creating_global_admin(seeded) -> None:
    factory, college, _other_college, student, _other_student, _manager, *_ = seeded
    actor = {"value": _admin(student.id, student.username, college_id=None)}
    async with _client(factory, actor) as client:
        tenant_required = await client.post(
            "/api/v2/users",
            json=_body("tenantless-user", None, role_codes=["STUDENT"]),
        )
        assert tenant_required.status_code == 422
        assert tenant_required.json()["code"] == "COLLEGE_REQUIRED"

        global_admin = await client.post(
            "/api/v2/users",
            json=_body("global-admin-test", None, role_codes=["SYS_ADMIN"]),
        )
        assert global_admin.status_code == 201
        assert global_admin.json()["data"]["college_id"] is None


@pytest.mark.asyncio
async def test_create_infers_the_only_active_college_and_allows_no_role(seeded) -> None:
    factory, college, other_college, student, *_ = seeded
    async with factory() as session:
        second_college = await session.get(College, other_college.id)
        assert second_college is not None
        second_college.status = 0
        await session.commit()

    actor = {"value": _admin(student.id, student.username, college_id=None)}
    async with _client(factory, actor) as client:
        created = await client.post(
            "/api/v2/users",
            json=_body("single-college-roleless", None, role_codes=[]),
        )

    assert created.status_code == 201
    assert created.json()["data"]["college_id"] == college.id
    assert created.json()["data"]["roles"] == []


@pytest.mark.asyncio
async def test_create_reports_when_user_disappears_before_post_commit_read(
    seeded, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory, college, _other_college, student, *_ = seeded
    original_commit = AsyncSession.commit
    original_scalar = AsyncSession.scalar

    async def commit_then_mark(session: AsyncSession) -> None:
        await original_commit(session)
        session.info["simulate_post_create_disappearance"] = True

    async def hide_post_commit_read(
        session: AsyncSession, statement: object, *args: object, **kwargs: object
    ):
        if session.info.pop("simulate_post_create_disappearance", False):
            return None
        return await original_scalar(session, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "commit", commit_then_mark)
    monkeypatch.setattr(AsyncSession, "scalar", hide_post_commit_read)
    actor = {"value": _admin(student.id, student.username, college.id)}
    async with _client(factory, actor) as client:
        response = await client.post(
            "/api/v2/users", json=_body("post-commit-read-race", college.id)
        )

    assert response.status_code == 404
    async with factory() as session:
        stored = await session.scalar(select(User).where(User.username == "post-commit-read-race"))
    assert stored is not None


@pytest.mark.asyncio
async def test_update_reports_when_user_disappears_before_post_commit_read(
    seeded, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory, college, _other_college, student, *_ = seeded
    original_commit = AsyncSession.commit
    original_scalar = AsyncSession.scalar

    async def commit_then_hide(session: AsyncSession) -> None:
        await original_commit(session)
        session.info["hide_next_updated_user_read"] = True

    async def hide_updated_user_read(
        session: AsyncSession, statement: object, *args: object, **kwargs: object
    ):
        if session.info.pop("hide_next_updated_user_read", False):
            return None
        return await original_scalar(session, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "commit", commit_then_hide)
    monkeypatch.setattr(AsyncSession, "scalar", hide_updated_user_read)
    actor = {"value": _admin(student.id, student.username, college.id)}
    async with _client(factory, actor) as client:
        response = await client.put(
            f"/api/v2/users/{student.id}",
            json=_body("student-a", college.id, real_name="提交后读取缺失"),
        )

    assert response.status_code == 404
    assert response.json()["code"] == "USER_NOT_FOUND"
    async with factory() as session:
        stored = await session.get(User, student.id)
    assert stored is not None
    assert stored.real_name == "提交后读取缺失"
