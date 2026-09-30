from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, timedelta

import pytest
from app.auth.csrf import enforce_csrf
from app.auth.security import Principal, get_current_principal
from app.core.settings import Settings
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.db.models import ReservationBlackout
from app.infrastructure.db.session import get_db
from app.main import create_app
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _principal(user_id: int, username: str, college_id: int | None, role: str) -> Principal:
    permissions = (
        ("device:read", "reservation-rule:manage")
        if role in {"LAB_ADMIN", "SYS_ADMIN"}
        else ("device:read",)
        if role == "STUDENT"
        else ()
    )
    return Principal(
        user_id=user_id,
        username=username,
        college_id=college_id,
        roles=(role,),
        token_type="access",
        token_id=f"scheduling-test-{user_id}",
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
async def test_blackout_create_duplicate_reactivate_delete_and_scope_guard(seeded) -> None:
    factory, college, _other_college, student, _other_student, manager, device, other_device = (
        seeded
    )
    blocked_date = date.today() + timedelta(days=60)
    body = {
        "scope_type": "DEVICE",
        "scope_id": device.id,
        "blocked_date": blocked_date.isoformat(),
        "reason": "  设备年度校准  ",
    }
    actor = {"value": _principal(manager.id, manager.username, college.id, "LAB_ADMIN")}
    async with _client(factory, actor) as client:
        created = await client.post("/api/v2/blackouts", json=body)
        assert created.status_code == 201
        first = created.json()["data"]
        assert first["reason"] == "设备年度校准"

        duplicate = await client.post("/api/v2/blackouts", json=body)
        assert duplicate.status_code == 409
        assert duplicate.json()["code"] == "BLACKOUT_EXISTS"

        deleted = await client.delete(f"/api/v2/blackouts/{first['id']}")
        assert deleted.status_code == 200

        reactivated = await client.post(
            "/api/v2/blackouts", json={**body, "reason": "延期后的校准"}
        )
        assert reactivated.status_code == 201
        assert reactivated.json()["data"]["id"] == first["id"]
        assert reactivated.json()["data"]["reason"] == "延期后的校准"
        assert reactivated.json()["data"]["active"] is True

        another_scope = await client.post(
            "/api/v2/blackouts",
            json={
                **body,
                "scope_id": other_device.id,
                "blocked_date": (blocked_date + timedelta(days=1)).isoformat(),
            },
        )
        assert another_scope.status_code == 403

        foreign_id = 987654
        missing_or_foreign = await client.delete(f"/api/v2/blackouts/{foreign_id}")
        assert missing_or_foreign.status_code == 404

    actor["value"] = _principal(student.id, student.username, college.id, "STUDENT")
    async with _client(factory, actor) as client:
        forbidden_create = await client.post("/api/v2/blackouts", json=body)
        assert forbidden_create.status_code == 403
        forbidden_delete = await client.delete(f"/api/v2/blackouts/{first['id']}")
        assert forbidden_delete.status_code == 403

    async with factory() as session:
        row = await session.get(ReservationBlackout, first["id"])
        assert row is not None
        assert row.active is True
        assert row.reason == "延期后的校准"


@pytest.mark.asyncio
async def test_blackout_list_filters_dates_inactive_rows_and_tenant_scopes(seeded) -> None:
    factory, college, other_college, student, other_student, manager, device, other_device = seeded
    assert device.lab_id is not None
    start = date.today() + timedelta(days=30)
    rows = [
        ReservationBlackout(
            scope_type="COLLEGE",
            scope_id=college.id,
            blocked_date=start,
            reason="院级检修",
            active=True,
            created_by=manager.id,
        ),
        ReservationBlackout(
            scope_type="LAB",
            scope_id=device.lab_id,
            blocked_date=start + timedelta(days=1),
            reason="实验室维护",
            active=True,
            created_by=manager.id,
        ),
        ReservationBlackout(
            scope_type="DEVICE",
            scope_id=device.id,
            blocked_date=start + timedelta(days=2),
            reason="设备校准",
            active=True,
            created_by=manager.id,
        ),
        ReservationBlackout(
            scope_type="DEVICE",
            scope_id=other_device.id,
            blocked_date=start + timedelta(days=2),
            reason="异学院维护",
            active=True,
            created_by=other_student.id,
        ),
        ReservationBlackout(
            scope_type="DEVICE",
            scope_id=device.id,
            blocked_date=start + timedelta(days=3),
            reason="已取消",
            active=False,
            created_by=manager.id,
        ),
    ]
    async with factory() as session:
        session.add_all(rows)
        await session.commit()
        start_id, end_id = rows[0].id, rows[2].id

    actor = {"value": _principal(student.id, student.username, college.id, "STUDENT")}
    async with _client(factory, actor) as client:
        filtered = await client.get(
            f"/api/v2/blackouts?start_date={start.isoformat()}"
            f"&end_date={(start + timedelta(days=2)).isoformat()}"
        )
        assert filtered.status_code == 200
        data = filtered.json()["data"]
        assert [row["scope_type"] for row in data] == ["COLLEGE", "LAB", "DEVICE"]
        assert [row["scope_name"] for row in data] == [
            college.name,
            "智能实验室",
            device.name,
        ]

        after_start = await client.get(
            f"/api/v2/blackouts?start_date={(start + timedelta(days=2)).isoformat()}"
        )
        assert {row["id"] for row in after_start.json()["data"]} == {end_id}

    actor["value"] = _principal(
        other_student.id, other_student.username, other_college.id, "STUDENT"
    )
    async with _client(factory, actor) as client:
        other_tenant = await client.get("/api/v2/blackouts")
    assert [row["scope_type"] for row in other_tenant.json()["data"]] == ["DEVICE"]
    assert other_tenant.json()["data"][0]["scope_name"] == other_device.name

    actor["value"] = _principal(manager.id, manager.username, None, "SYS_ADMIN")
    async with _client(factory, actor) as client:
        global_view = await client.get("/api/v2/blackouts")
    assert len(global_view.json()["data"]) == 4
    assert start_id in {row["id"] for row in global_view.json()["data"]}
