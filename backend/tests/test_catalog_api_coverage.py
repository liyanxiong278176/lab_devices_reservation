from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from app.api.v2 import catalog
from app.auth.csrf import enforce_csrf
from app.auth.security import Principal, get_current_principal
from app.core.settings import Settings
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.db.models import College, DeviceCategory
from app.infrastructure.db.session import get_db
from app.main import create_app
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _principal(
    user_id: int, college_id: int | None, *roles: str, permissions: tuple[str, ...]
) -> Principal:
    return Principal(
        user_id=user_id,
        username=f"catalog-{user_id}",
        college_id=college_id,
        roles=roles,
        token_type="access",
        token_id=f"catalog-token-{user_id}",
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
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def _admin(user_id: int) -> Principal:
    return _principal(
        user_id,
        None,
        "SYS_ADMIN",
        permissions=("organization:read", "organization:manage"),
    )


@pytest.mark.asyncio
async def test_college_and_manager_lists_apply_role_and_tenant_scope(
    seeded, tmp_path: Path
) -> None:
    factory, college, other_college, student, _other_student, manager, *_ = seeded
    async with factory() as session:
        row = await session.get(College, college.id)
        assert row is not None
        row.manager_id = manager.id
        await session.commit()

    actor = {"value": _principal(student.id, college.id, "STUDENT", permissions=())}
    async with _client(factory, actor, tmp_path) as client:
        forbidden = await client.get("/api/v2/colleges")
        assert forbidden.status_code == 403

        actor["value"] = _principal(
            manager.id, college.id, "LAB_ADMIN", permissions=("organization:read",)
        )
        scoped = await client.get("/api/v2/colleges")
        assert [row["id"] for row in scoped.json()["data"]] == [college.id]
        assert scoped.json()["data"][0]["manager_name"] == "负责人"
        manager_forbidden = await client.get(
            "/api/v2/organization/managers", params={"college_id": college.id}
        )
        assert manager_forbidden.status_code == 403

        actor["value"] = _admin(manager.id)
        all_colleges = await client.get("/api/v2/colleges")
        assert {row["id"] for row in all_colleges.json()["data"]} == {college.id, other_college.id}
        managers = await client.get(
            "/api/v2/organization/managers", params={"college_id": college.id}
        )
        assert [row["id"] for row in managers.json()["data"]] == [manager.id]
        inactive_college = await client.get(
            "/api/v2/organization/managers", params={"college_id": 999999}
        )
        assert inactive_college.status_code == 422


@pytest.mark.asyncio
async def test_college_create_update_duplicate_manager_and_integrity_race_paths(
    seeded, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory, college, _other_college, student, _other_student, manager, *_ = seeded
    actor = {"value": _admin(manager.id)}
    monkeypatch.setattr(catalog, "sync_catalog_cache_bump", AsyncMock(return_value=True))
    async with _client(factory, actor, tmp_path) as client:
        created = await client.post(
            "/api/v2/colleges",
            json={"code": "  new-1 ", "name": " 新学院 "},
        )
        assert created.status_code == 201
        created_id = created.json()["data"]["id"]
        assert created.json()["data"]["code"] == "NEW-1"
        assert created.json()["data"]["manager_name"] is None

        duplicate = await client.post("/api/v2/colleges", json={"code": "cse", "name": "新名字"})
        assert duplicate.status_code == 409
        duplicate_update = await client.put(
            f"/api/v2/colleges/{created_id}", json={"code": "BIO", "name": "新学院"}
        )
        assert duplicate_update.status_code == 409
        missing = await client.put(
            "/api/v2/colleges/999999", json={"code": "NONE", "name": "不存在"}
        )
        assert missing.status_code == 422
        missing_manager = await client.put(
            f"/api/v2/colleges/{created_id}",
            json={"code": "NEW-1", "name": "新学院", "manager_id": 999999},
        )
        assert missing_manager.status_code == 422
        assert missing_manager.json()["code"] == "MANAGER_INVALID"
        async with factory() as session:
            current_student = await session.get(type(student), student.id)
            assert current_student is not None
            current_student.college_id = created_id
            await session.commit()
        invalid_manager = await client.put(
            f"/api/v2/colleges/{created_id}",
            json={"code": "NEW-1", "name": "新学院", "manager_id": student.id},
        )
        assert invalid_manager.status_code == 422
        assert invalid_manager.json()["code"] == "MANAGER_ROLE_REQUIRED"
        async with factory() as session:
            current_manager = await session.get(type(manager), manager.id)
            assert current_manager is not None
            current_manager.college_id = created_id
            await session.commit()
        updated = await client.put(
            f"/api/v2/colleges/{created_id}",
            json={"code": "new-1b", "name": " 更新学院 ", "manager_id": manager.id},
        )
        assert updated.status_code == 200
        assert updated.json()["data"]["manager_id"] == manager.id
        assert updated.json()["data"]["manager_name"] == "负责人"
        assert updated.json()["data"]["name"] == "更新学院"
        cleared = await client.put(
            f"/api/v2/colleges/{created_id}",
            json={"code": "new-1b", "name": "更新学院", "manager_id": None},
        )
        assert cleared.status_code == 200
        assert cleared.json()["data"]["manager_id"] is None

        async def concurrent_college_insert(session, _manager_id, _college_id):
            session.add(College(code="RACE-1", name="并发写入者"))
            return None

        monkeypatch.setattr(catalog, "_resolve_manager", concurrent_college_insert)
        commit_race = await client.post(
            "/api/v2/colleges", json={"code": "race-1", "name": "竞态失败学院"}
        )
        assert commit_race.status_code == 409
        assert commit_race.json()["code"] == "COLLEGE_EXISTS"

        async def concurrent_update_insert(session, _manager_id, _college_id):
            session.add(College(code="RACE-2", name="并发更新者"))
            return None

        monkeypatch.setattr(catalog, "_resolve_manager", concurrent_update_insert)
        update_race = await client.put(
            f"/api/v2/colleges/{college.id}", json={"code": "RACE-2", "name": "更新竞态"}
        )
        assert update_race.status_code == 409
        assert update_race.json()["code"] == "COLLEGE_EXISTS"


@pytest.mark.asyncio
async def test_lab_create_update_scope_and_validation_paths(
    seeded, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory, college, other_college, student, _other_student, manager, device, _other_device = (
        seeded
    )
    monkeypatch.setattr(catalog, "sync_catalog_cache_bump", AsyncMock(return_value=True))
    actor = {"value": _principal(student.id, college.id, "STUDENT", permissions=())}
    async with _client(factory, actor, tmp_path) as client:
        forbidden = await client.get("/api/v2/labs")
        assert forbidden.status_code == 403
        actor["value"] = _principal(
            manager.id, college.id, "LAB_ADMIN", permissions=("organization:read",)
        )
        scoped = await client.get("/api/v2/labs", params={"page": 1, "size": 5})
        assert scoped.status_code == 200
        assert scoped.json()["data"]["total"] == 1
        assert scoped.json()["data"]["records"][0]["manager_name"] == "负责人"

        actor["value"] = _admin(manager.id)
        all_labs = await client.get("/api/v2/labs")
        assert all_labs.json()["data"]["total"] == 1
        missing_college = await client.post(
            "/api/v2/labs", json={"college_id": 999999, "name": "新实验室"}
        )
        assert missing_college.status_code == 422
        invalid_manager = await client.post(
            "/api/v2/labs",
            json={"college_id": college.id, "name": "坏负责人", "manager_id": student.id},
        )
        assert invalid_manager.status_code == 422

        created = await client.post(
            "/api/v2/labs",
            json={
                "college_id": college.id,
                "name": " 空白信息实验室 ",
                "location": "  ",
                "description": None,
            },
        )
        assert created.status_code == 201
        lab_id = created.json()["data"]["id"]
        assert created.json()["data"]["location"] is None
        assert created.json()["data"]["manager_name"] is None

        missing = await client.put(
            "/api/v2/labs/999999", json={"college_id": college.id, "name": "无效"}
        )
        assert missing.status_code == 404
        immutable = await client.put(
            f"/api/v2/labs/{device.lab_id}",
            json={"college_id": other_college.id, "name": "跨学院迁移"},
        )
        assert immutable.status_code == 409
        changed = await client.put(
            f"/api/v2/labs/{lab_id}",
            json={
                "college_id": college.id,
                "name": "已更新实验室",
                "location": "  ",
                "description": "  ",
            },
        )
        assert changed.status_code == 200
        assert changed.json()["data"]["location"] is None
        assert changed.json()["data"]["description"] is None

        async with factory() as session:
            current_college = await session.get(College, other_college.id)
            assert current_college is not None
            current_college.status = 0
            await session.commit()
        inactive = await client.post(
            "/api/v2/labs", json={"college_id": other_college.id, "name": "停用学院实验室"}
        )
        assert inactive.status_code == 422


@pytest.mark.asyncio
async def test_category_tree_builds_roots_for_orphan_and_zero_parent_nodes(
    seeded, tmp_path: Path
) -> None:
    factory, _, _, student, *_ = seeded
    async with factory() as session:
        session.add_all(
            [
                DeviceCategory(id=0, name="zero", parent_id=0, sort=0),
                DeviceCategory(id=1, name="root", parent_id=0, sort=1),
                DeviceCategory(id=2, name="child", parent_id=1, sort=2),
                DeviceCategory(id=3, name="orphan", parent_id=999, sort=3),
            ]
        )
        await session.commit()
    actor = {"value": _principal(student.id, None, "STUDENT", permissions=())}
    async with _client(factory, actor, tmp_path) as client:
        response = await client.get("/api/v2/device-categories")
    assert response.status_code == 200
    rows = response.json()["data"]
    root = next(row for row in rows if row["name"] == "root")
    orphan = next(row for row in rows if row["name"] == "orphan")
    zero = next(row for row in rows if row["name"] == "zero")
    assert [row["name"] for row in root["children"]] == ["child"]
    assert orphan["children"] == []
    assert zero["children"] == []
