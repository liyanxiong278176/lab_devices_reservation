from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from app.auth.csrf import enforce_csrf
from app.auth.security import Principal, get_current_principal
from app.core.settings import Settings
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.db.session import get_db
from app.main import create_app
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _principal(user_id: int, username: str, college_id: int, role: str) -> Principal:
    permissions = (
        ("reservation-rule:manage", "reservation:create")
        if role in {"LAB_ADMIN", "SYS_ADMIN"}
        else ()
    )
    return Principal(
        user_id=user_id,
        username=username,
        college_id=college_id,
        roles=(role,),
        token_type="access",
        token_id=f"reservation-rule-test-{user_id}",
        permissions=permissions,
    )


@asynccontextmanager
async def _client(
    session_factory: async_sessionmaker[AsyncSession],
    actor: dict[str, Principal],
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
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_manager_can_only_manage_rules_in_owned_scope(seeded) -> None:
    factory, college, _other_college, student, _other_student, manager, device, other_device = (
        seeded
    )
    assert device.lab_id is not None
    actor = {"value": _principal(manager.id, manager.username, college.id, "LAB_ADMIN")}
    lab_body = {
        "scope_type": "LAB",
        "scope_id": device.lab_id,
        "user_category": "STUDENT",
        "max_booking_days": 4,
        "max_advance_days": 45,
        "approval_required": False,
    }
    async with _client(factory, actor) as client:
        global_denied = await client.put(
            "/api/v2/reservation-rules",
            json={
                "scope_type": "GLOBAL",
                "scope_id": 0,
                "user_category": "ALL",
                "max_booking_days": 3,
            },
        )
        assert global_denied.status_code == 403

        created = await client.put("/api/v2/reservation-rules", json=lab_body)
        assert created.status_code == 200
        first = created.json()["data"]
        assert first["scope_name"] == "智能实验室"

        updated = await client.put(
            "/api/v2/reservation-rules",
            json={**lab_body, "max_booking_days": 5, "approval_required": True},
        )
        assert updated.status_code == 200
        assert updated.json()["data"]["id"] == first["id"]
        assert updated.json()["data"]["max_booking_days"] == 5

        listed = await client.get(
            "/api/v2/reservation-rules?scope_type=LAB&user_category=STUDENT"
            f"&scope_id={device.lab_id}&page=1&page_size=10"
        )
        assert listed.status_code == 200
        assert listed.json()["data"]["total"] == 1
        assert listed.json()["data"]["items"][0]["id"] == first["id"]

        other_scope = await client.put(
            "/api/v2/reservation-rules",
            json={
                "scope_type": "DEVICE",
                "scope_id": other_device.id,
                "user_category": "ALL",
                "max_advance_days": 10,
            },
        )
        assert other_scope.status_code == 403

        deleted = await client.delete(f"/api/v2/reservation-rules/{first['id']}")
        assert deleted.status_code == 200
        missing = await client.delete(f"/api/v2/reservation-rules/{first['id']}")
        assert missing.status_code == 404

    actor["value"] = _principal(student.id, student.username, college.id, "STUDENT")
    async with _client(factory, actor) as client:
        forbidden = await client.get("/api/v2/reservation-rules")
    assert forbidden.status_code == 403


@pytest.mark.asyncio
async def test_system_admin_manages_global_college_and_device_rules(seeded) -> None:
    factory, college, _other_college, student, _other_student, _manager, _device, other_device = (
        seeded
    )
    actor = {"value": _principal(student.id, student.username, college.id, "SYS_ADMIN")}
    async with _client(factory, actor) as client:
        global_rule = await client.put(
            "/api/v2/reservation-rules",
            json={
                "scope_type": "GLOBAL",
                "scope_id": 0,
                "user_category": "ALL",
                "max_booking_days": 7,
            },
        )
        assert global_rule.status_code == 200
        assert global_rule.json()["data"]["scope_name"] == "全校默认"

        college_rule = await client.put(
            "/api/v2/reservation-rules",
            json={
                "scope_type": "COLLEGE",
                "scope_id": college.id,
                "user_category": "STUDENT",
                "max_advance_days": 90,
            },
        )
        assert college_rule.status_code == 200
        assert college_rule.json()["data"]["scope_name"] == college.name

        device_rule = await client.put(
            "/api/v2/reservation-rules",
            json={
                "scope_type": "DEVICE",
                "scope_id": other_device.id,
                "user_category": "ALL",
                "approval_required": True,
            },
        )
        assert device_rule.status_code == 200
        assert device_rule.json()["data"]["scope_name"] == other_device.name

        all_rules = await client.get("/api/v2/reservation-rules")
        assert all_rules.status_code == 200
        assert all_rules.json()["data"]["total"] == 3
        assert {row["scope_type"] for row in all_rules.json()["data"]["items"]} == {
            "GLOBAL",
            "COLLEGE",
            "DEVICE",
        }

        deleted = await client.delete(
            f"/api/v2/reservation-rules/{device_rule.json()['data']['id']}"
        )
        assert deleted.status_code == 200

        invalid = await client.put(
            "/api/v2/reservation-rules",
            json={"scope_type": "GLOBAL", "scope_id": 9, "user_category": "ALL"},
        )
        assert invalid.status_code == 422

        missing_scope = await client.put(
            "/api/v2/reservation-rules",
            json={
                "scope_type": "COLLEGE",
                "scope_id": 0,
                "user_category": "ALL",
                "max_booking_days": 3,
            },
        )
        assert missing_scope.status_code == 422

        missing_limit = await client.put(
            "/api/v2/reservation-rules",
            json={"scope_type": "GLOBAL", "scope_id": 0, "user_category": "ALL"},
        )
        assert missing_limit.status_code == 422


@pytest.mark.asyncio
async def test_unique_rule_race_is_returned_as_a_conflict(
    seeded, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory, college, _other_college, _student, _other_student, manager, device, _other_device = (
        seeded
    )
    assert device.lab_id is not None
    actor = {"value": _principal(manager.id, manager.username, college.id, "LAB_ADMIN")}
    async with _client(factory, actor) as client:

        async def duplicate_during_insert(
            session: AsyncSession, *_args: object, **_kwargs: object
        ) -> None:
            raise IntegrityError("INSERT reservation_rule", {}, RuntimeError("unique collision"))

        monkeypatch.setattr(AsyncSession, "flush", duplicate_during_insert)
        response = await client.put(
            "/api/v2/reservation-rules",
            json={
                "scope_type": "LAB",
                "scope_id": device.lab_id,
                "user_category": "LAB_ADMIN",
                "max_booking_days": 2,
            },
        )

    assert response.status_code == 409
    assert response.json()["code"] == "RULE_CONFLICT"
