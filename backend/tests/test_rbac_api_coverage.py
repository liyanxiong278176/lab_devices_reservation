from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from app.auth.csrf import enforce_csrf
from app.auth.security import Principal, get_current_principal
from app.core.settings import Settings
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.db.models import AuthorizationVersion, Role, User
from app.infrastructure.db.session import get_db
from app.main import create_app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload


def _principal(
    user_id: int,
    username: str,
    college_id: int | None,
    *roles: str,
    permissions: tuple[str, ...] = (),
) -> Principal:
    return Principal(
        user_id=user_id,
        username=username,
        college_id=college_id,
        roles=roles,
        token_type="access",
        token_id=f"rbac-{user_id}",
        permissions=permissions,
    )


@asynccontextmanager
async def _client(
    session_factory: async_sessionmaker[AsyncSession],
    actor: dict[str, Principal],
    upload_dir: Path,
) -> AsyncIterator[AsyncClient]:
    app = create_app(
        Settings(
            environment="test",
            mysql_dsn="sqlite+aiosqlite:///:memory:",
            cors_origins=["http://test"],
            redis_url="redis://127.0.0.1:6379/15",
            enable_workers=False,
            rate_limit_enabled=False,
            upload_dir=str(upload_dir),
        )
    )

    async def override_db():
        async with session_factory() as session:
            yield session

    async def override_actor() -> Principal:
        return actor["value"]

    async def noop() -> None:
        return None

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_principal] = override_actor
    app.dependency_overrides[enforce_csrf] = noop
    app.dependency_overrides[enforce_authenticated_rate_limit] = noop
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_rbac_roles_permissions_and_authorization_version_lifecycle(
    seeded, tmp_path: Path
) -> None:
    factory, college, _other_college, student, _other_student, manager, *_ = seeded
    actor = {
        "value": _principal(
            manager.id,
            manager.username,
            None,
            "SYS_ADMIN",
            permissions=("rbac:manage",),
        )
    }
    async with _client(factory, actor, tmp_path) as client:
        non_admin = _principal(
            manager.id,
            manager.username,
            college.id,
            "LAB_ADMIN",
            permissions=("rbac:manage",),
        )
        actor["value"] = non_admin
        forbidden = await client.get("/api/v2/rbac/roles")
        assert forbidden.status_code == 403
        actor["value"] = _principal(student.id, student.username, college.id, "STUDENT")
        student_forbidden = await client.get("/api/v2/rbac/permissions")
        assert student_forbidden.status_code == 403
        actor["value"] = _principal(
            manager.id,
            manager.username,
            None,
            "SYS_ADMIN",
            permissions=("rbac:manage",),
        )

        permissions = await client.get("/api/v2/rbac/permissions")
        assert permissions.status_code == 200
        permission_codes = {item["code"] for item in permissions.json()["data"]}
        assert {"device:read", "reservation:read:own", "rbac:manage"} <= permission_codes

        system_roles = await client.get("/api/v2/rbac/roles")
        assert system_roles.status_code == 200
        student_role = next(row for row in system_roles.json()["data"] if row["code"] == "STUDENT")
        system_role = next(row for row in system_roles.json()["data"] if row["code"] == "SYS_ADMIN")

        invalid_code = await client.post(
            "/api/v2/rbac/roles",
            json={"role_code": "OPS-LEAD", "role_name": "Ops", "permission_codes": []},
        )
        assert invalid_code.status_code == 422
        existing = await client.post(
            "/api/v2/rbac/roles",
            json={"role_code": "STUDENT", "role_name": "Duplicate", "permission_codes": []},
        )
        assert existing.status_code == 409
        duplicate_permissions = await client.post(
            "/api/v2/rbac/roles",
            json={
                "role_code": "LAB_ASSISTANT",
                "role_name": "Assistant",
                "permission_codes": ["device:read", " device:read "],
            },
        )
        assert duplicate_permissions.status_code == 422
        reserved_permission = await client.post(
            "/api/v2/rbac/roles",
            json={
                "role_code": "LAB_ASSISTANT",
                "role_name": "Assistant",
                "permission_codes": ["rbac:manage"],
            },
        )
        assert reserved_permission.status_code == 409
        unknown_permission = await client.post(
            "/api/v2/rbac/roles",
            json={
                "role_code": "LAB_ASSISTANT",
                "role_name": "Assistant",
                "permission_codes": ["unknown:permission"],
            },
        )
        assert unknown_permission.status_code == 422

        created = await client.post(
            "/api/v2/rbac/roles",
            json={
                "role_code": " lab_assistant ",
                "role_name": "  Lab assistant  ",
                "permission_codes": ["device:read"],
            },
        )
        assert created.status_code == 201
        role = created.json()["data"]
        role_id = role["id"]
        assert role["code"] == "LAB_ASSISTANT"
        assert role["name"] == "Lab assistant"
        assert role["permissions"] == ["device:read"]
        async with factory() as session:
            version = await session.scalar(
                select(AuthorizationVersion.version).where(AuthorizationVersion.id == 1)
            )
            assert version == 2

        missing_rename = await client.patch(
            "/api/v2/rbac/roles/999999", json={"role_name": "Missing"}
        )
        assert missing_rename.status_code == 404
        protected_rename = await client.patch(
            f"/api/v2/rbac/roles/{student_role['id']}", json={"role_name": "Student"}
        )
        assert protected_rename.status_code == 409
        renamed = await client.patch(
            f"/api/v2/rbac/roles/{role_id}", json={"role_name": "  Equipment assistant  "}
        )
        assert renamed.status_code == 200
        assert renamed.json()["data"]["name"] == "Equipment assistant"

        missing_permissions = await client.put(
            "/api/v2/rbac/roles/999999/permissions", json={"permission_codes": []}
        )
        assert missing_permissions.status_code == 404
        protected_permissions = await client.put(
            f"/api/v2/rbac/roles/{system_role['id']}/permissions",
            json={"permission_codes": []},
        )
        assert protected_permissions.status_code == 409
        empty_permissions = await client.put(
            f"/api/v2/rbac/roles/{role_id}/permissions", json={"permission_codes": []}
        )
        assert empty_permissions.status_code == 200
        assert empty_permissions.json()["data"]["permissions"] == []
        valid_permissions = await client.put(
            f"/api/v2/rbac/roles/{role_id}/permissions",
            json={"permission_codes": ["device:read", "reservation:read:own"]},
        )
        assert valid_permissions.status_code == 200
        assert valid_permissions.json()["data"]["permissions"] == [
            "device:read",
            "reservation:read:own",
        ]

        duplicate_update = await client.put(
            f"/api/v2/rbac/roles/{role_id}/permissions",
            json={"permission_codes": ["device:read", "device:read"]},
        )
        assert duplicate_update.status_code == 422
        reserved_update = await client.put(
            f"/api/v2/rbac/roles/{role_id}/permissions",
            json={"permission_codes": ["user:manage"]},
        )
        assert reserved_update.status_code == 409
        unknown_update = await client.put(
            f"/api/v2/rbac/roles/{role_id}/permissions",
            json={"permission_codes": ["missing:permission"]},
        )
        assert unknown_update.status_code == 422

        async with factory() as session:
            custom_role = await session.get(Role, role_id)
            current_student = await session.scalar(
                select(User).options(selectinload(User.roles)).where(User.id == student.id)
            )
            current_student.roles.append(custom_role)
            await session.commit()
        in_use = await client.delete(f"/api/v2/rbac/roles/{role_id}")
        assert in_use.status_code == 409
        protected_delete = await client.delete(f"/api/v2/rbac/roles/{system_role['id']}")
        assert protected_delete.status_code == 409
        missing_delete = await client.delete("/api/v2/rbac/roles/999999")
        assert missing_delete.status_code == 404

        async with factory() as session:
            custom_role = await session.get(Role, role_id)
            current_student = await session.scalar(
                select(User).options(selectinload(User.roles)).where(User.id == student.id)
            )
            current_student.roles.remove(custom_role)
            await session.commit()
        deleted = await client.delete(f"/api/v2/rbac/roles/{role_id}")
        assert deleted.status_code == 200

    async with factory() as session:
        assert await session.get(Role, role_id) is None
        version = await session.scalar(
            select(AuthorizationVersion.version).where(AuthorizationVersion.id == 1)
        )
        assert version == 5
