from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.api.v2 import devices
from app.auth.csrf import enforce_csrf
from app.auth.security import Principal, get_current_principal
from app.core.settings import Settings
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.db.models import (
    College,
    Device,
    DeviceCategory,
    DeviceStatusHistory,
    Lab,
    OutboxTask,
    RepairReport,
    Reservation,
    ReservationItem,
    ReservationRule,
)
from app.infrastructure.db.session import get_db
from app.main import create_app
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


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
        token_id=f"devices-{user_id}",
        permissions=permissions,
    )


def _student_principal(user_id: int, username: str, college_id: int) -> Principal:
    return _principal(user_id, username, college_id, "STUDENT", permissions=("device:read",))


def _manager(user_id: int, username: str, college_id: int) -> Principal:
    return _principal(
        user_id,
        username,
        college_id,
        "LAB_ADMIN",
        permissions=("device:read", "device:manage"),
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


def _patch_cache(monkeypatch) -> None:
    monkeypatch.setattr(devices, "get_redis", lambda _request: None)
    monkeypatch.setattr(devices, "get_redis_circuit", lambda _app: None)
    monkeypatch.setattr(devices, "CacheService", lambda *_args: None)
    monkeypatch.setattr(devices, "sync_catalog_cache_bump", AsyncMock(return_value=True))


def _device_payload(lab_id: int, **changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "  Managed workstation  ",
        "lab_id": lab_id,
        "need_approval": False,
        "max_reservation_days": 8,
        "accessory_checklist": [" keyboard ", "", "mouse"],
    }
    payload.update(changes)
    return payload


@pytest.mark.asyncio
async def test_device_request_normalizes_accessories_and_rejects_duplicate_or_long_values() -> None:
    from app.api.v2.devices import DeviceCreateRequest

    normalized = DeviceCreateRequest(
        name="workstation", lab_id=1, accessory_checklist=[" cable ", "", "adapter"]
    )
    assert normalized.accessory_checklist == ["cable", "adapter"]

    with pytest.raises(ValidationError, match="不能包含重复项目"):
        DeviceCreateRequest(name="workstation", lab_id=1, accessory_checklist=["cable", " cable "])
    with pytest.raises(ValidationError, match="不能超过 100 个字符"):
        DeviceCreateRequest(name="workstation", lab_id=1, accessory_checklist=["x" * 101])


@pytest.mark.asyncio
async def test_manager_access_policy_and_device_rule_insert_update_and_race_recovery(
    seeded, monkeypatch
) -> None:
    factory, college, other_college, _student, other_student, manager, device, _other_device = (
        seeded
    )
    async with factory() as session:
        lab = await session.get(Lab, device.lab_id)
        assert await devices._manager_can_access(
            session,
            _principal(manager.id, manager.username, college.id, "SYS_ADMIN"),
            lab,
        )
        assert not await devices._manager_can_access(
            session, _student_principal(manager.id, manager.username, college.id), lab
        )
        assert not await devices._manager_can_access(
            session,
            _manager(manager.id, manager.username, other_college.id),
            lab,
        )
        assert await devices._manager_can_access(
            session, _manager(manager.id, manager.username, college.id), lab
        )

        delegated_id = other_student.id
        delegated = _manager(delegated_id, other_student.username, college.id)
        lab.manager_id = manager.id
        college_row = await session.get(College, college.id)
        college_row.manager_id = delegated_id
        await session.commit()
        assert await devices._manager_can_access(session, delegated, lab)
        college_row.manager_id = None
        await session.flush()
        assert not await devices._manager_can_access(session, delegated, lab)

    async with factory() as session:
        rule = ReservationRule(
            scope_type="DEVICE",
            scope_id=device.id,
            user_category="ALL",
            max_booking_days=3,
            max_advance_days=10,
            approval_required=False,
            created_by=manager.id,
            updated_by=manager.id,
        )
        session.add(rule)
        await session.commit()
        current_device = await session.get(Device, device.id)
        current_device.max_reservation_days = 6
        current_device.max_advance_days = 40
        current_device.need_approval = True

        original_scalar = session.scalar
        scalar_calls = 0

        async def miss_then_read(statement):
            nonlocal scalar_calls
            scalar_calls += 1
            if scalar_calls == 1:
                return None
            return await original_scalar(statement)

        monkeypatch.setattr(session, "scalar", miss_then_read)
        await devices._sync_device_reservation_rule(session, current_device, manager.id)
        assert scalar_calls == 2
        assert rule.max_booking_days == 6
        assert rule.max_advance_days == 40
        assert rule.approval_required is True
        assert rule.updated_by == manager.id
        await session.commit()

    async with factory() as session:
        current_device = await session.get(Device, device.id)

        async def cannot_observe_concurrent_insert(_statement):
            return None

        monkeypatch.setattr(session, "scalar", cannot_observe_concurrent_insert)
        with pytest.raises(IntegrityError):
            await devices._sync_device_reservation_rule(session, current_device, manager.id)
        await session.rollback()

    class MySQLSession:
        def __init__(self) -> None:
            self.statement = None

        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="mysql"))

        async def execute(self, statement):
            self.statement = statement

    mysql_session = MySQLSession()
    await devices._sync_device_reservation_rule(mysql_session, device, manager.id)
    assert mysql_session.statement is not None
    from sqlalchemy.dialects import mysql

    assert "ON DUPLICATE KEY UPDATE" in str(
        mysql_session.statement.compile(dialect=mysql.dialect())
    )


@pytest.mark.asyncio
async def test_device_listing_detail_and_availability_cover_access_and_date_validation(
    seeded, tmp_path: Path, monkeypatch
) -> None:
    factory, college, _other_college, student, _other_student, manager, device, other_device = (
        seeded
    )
    _patch_cache(monkeypatch)
    actor = {"value": _manager(manager.id, manager.username, college.id)}
    start = date.today() + timedelta(days=3)
    async with _client(factory, actor, tmp_path) as client:
        listed = await client.get("/api/v2/devices", params={"search": "GPU", "page_size": 5})
        assert listed.status_code == 200
        assert listed.json()["data"]["total"] == 1
        assert listed.json()["data"]["items"][0]["id"] == device.id

        detail = await client.get(f"/api/v2/devices/{device.id}")
        assert detail.status_code == 200
        assert detail.json()["data"]["name"] == "GPU 工作站"

        foreign_detail = await client.get(f"/api/v2/devices/{other_device.id}")
        assert foreign_detail.status_code == 404

        invalid_date = await client.get(
            f"/api/v2/devices/{device.id}/availability",
            params={"start_date": "2026-13-01", "end_date": "2026-13-02"},
        )
        assert invalid_date.status_code == 422
        assert invalid_date.json()["code"] == "DATE_INVALID"

        invalid_range = await client.get(
            f"/api/v2/devices/{device.id}/availability",
            params={
                "start_date": (start + timedelta(days=2)).isoformat(),
                "end_date": start.isoformat(),
            },
        )
        assert invalid_range.status_code == 422
        assert invalid_range.json()["code"] == "DATE_RANGE_INVALID"

        availability = await client.get(
            f"/api/v2/devices/{device.id}/availability",
            params={
                "start_date": start.isoformat(),
                "end_date": (start + timedelta(days=1)).isoformat(),
            },
        )
        assert availability.status_code == 200
        assert len(availability.json()["data"]) == 2
        assert all(day["available"] for day in availability.json()["data"])

        actor["value"] = _student_principal(student.id, student.username, college.id)
        no_permission = await client.get(f"/api/v2/devices/{device.id}")
        assert no_permission.status_code == 200

        actor["value"] = _principal(student.id, student.username, college.id, "STUDENT")
        forbidden_list = await client.get("/api/v2/devices")
        assert forbidden_list.status_code == 403
        forbidden_detail = await client.get(f"/api/v2/devices/{device.id}")
        assert forbidden_detail.status_code == 403
        forbidden_availability = await client.get(
            f"/api/v2/devices/{device.id}/availability",
            params={"start_date": start.isoformat(), "end_date": start.isoformat()},
        )
        assert forbidden_availability.status_code == 403


@pytest.mark.asyncio
async def test_device_create_update_and_tenant_validation(
    seeded, tmp_path: Path, monkeypatch
) -> None:
    factory, college, other_college, _student, other_student, manager, device, other_device = seeded
    _patch_cache(monkeypatch)
    actor = {"value": _manager(manager.id, manager.username, college.id)}
    async with factory() as session:
        unmanaged_lab = Lab(
            college_id=college.id,
            name="另一个负责人管理的实验室",
            manager_id=other_student.id,
            status=1,
        )
        unmanaged_device = Device(
            college_id=college.id,
            lab=unmanaged_lab,
            name="Unmanaged device",
            status="IDLE",
        )
        category = DeviceCategory(name="Coverage category")
        session.add_all([unmanaged_lab, unmanaged_device, category])
        await session.commit()
        unmanaged_device_id = unmanaged_device.id
        category_id = category.id
    async with _client(factory, actor, tmp_path) as client:
        invalid_manager = await client.post(
            "/api/v2/devices",
            json=_device_payload(other_device.lab_id or 999999),
        )
        assert invalid_manager.status_code == 403

        invalid_accessories = await client.post(
            "/api/v2/devices",
            json=_device_payload(device.lab_id, accessory_checklist=["case", " case "]),
        )
        assert invalid_accessories.status_code == 422
        validation_error = invalid_accessories.json()["data"]["errors"][0]
        assert validation_error["loc"] == ["body", "accessory_checklist"]
        assert "input" not in validation_error
        assert "ctx" not in validation_error

        created = await client.post(
            "/api/v2/devices",
            json=_device_payload(device.lab_id, asset_code="NEW-DEVICE-1", need_approval=False),
        )
        assert created.status_code == 201
        created_data = created.json()["data"]
        created_id = created_data["id"]
        assert created_data["name"] == "Managed workstation"
        assert created_data["accessory_checklist"] == ["keyboard", "mouse"]

        payload = _device_payload(
            device.lab_id,
            name="  Updated workstation ",
            asset_code="NEW-DEVICE-1",
            need_approval=True,
            max_reservation_days=5,
            max_advance_days=45,
            category_id=category_id,
        )
        unmanaged_update = await client.put(
            f"/api/v2/devices/{unmanaged_device_id}",
            json=payload,
        )
        assert unmanaged_update.status_code == 403

        outside_lab = await client.put(
            f"/api/v2/devices/{device.id}",
            json={**payload, "lab_id": 999999},
        )
        assert outside_lab.status_code == 403

        missing_category = await client.put(
            f"/api/v2/devices/{created_id}",
            json={**payload, "category_id": 999999},
        )
        assert missing_category.status_code == 422
        assert missing_category.json()["code"] == "CATEGORY_NOT_FOUND"

        updated = await client.put(f"/api/v2/devices/{created_id}", json=payload)
        assert updated.status_code == 200
        assert updated.json()["data"]["name"] == "Updated workstation"
        assert updated.json()["data"]["need_approval"] is True

        unchanged_policy = await client.put(f"/api/v2/devices/{created_id}", json=payload)
        assert unchanged_policy.status_code == 200

        clear_category = await client.put(
            f"/api/v2/devices/{created_id}",
            json={**payload, "category_id": None},
        )
        assert clear_category.status_code == 200

        async with factory() as session:
            rule = await session.scalar(
                select(ReservationRule).where(
                    ReservationRule.scope_type == "DEVICE",
                    ReservationRule.scope_id == created_id,
                    ReservationRule.user_category == "ALL",
                )
            )
            assert rule is not None
            assert rule.max_booking_days == 5
            assert rule.max_advance_days == 45
            assert rule.approval_required is True

        actor["value"] = _principal(manager.id, manager.username, college.id, "LAB_ADMIN")
        forbidden_update = await client.put(f"/api/v2/devices/{created_id}", json=payload)
        assert forbidden_update.status_code == 403


@pytest.mark.asyncio
async def test_device_status_change_notifies_reservations_and_delete_guards(
    seeded, tmp_path: Path, monkeypatch
) -> None:
    factory, college, _other_college, student, _other_student, manager, device, _other_device = (
        seeded
    )
    _patch_cache(monkeypatch)
    actor = {"value": _manager(manager.id, manager.username, college.id)}
    start = date.today() + timedelta(days=10)
    timestamp = datetime.combine(date.today(), datetime.min.time())
    async with factory() as session:
        unmanaged_lab = Lab(
            college_id=college.id,
            name="Unmanaged status lab",
            manager_id=_other_student.id,
            status=1,
        )
        unmanaged_device = Device(
            college_id=college.id,
            lab=unmanaged_lab,
            name="Unmanaged status device",
            status="IDLE",
        )
        session.add_all([unmanaged_lab, unmanaged_device])
        await session.flush()
        pending = Reservation(
            college_id=college.id,
            user_id=student.id,
            device_id=device.id,
            purpose="pending request",
            purpose_category="RESEARCH",
            start_date=start,
            end_date=start,
            status="PENDING",
            created_at=timestamp,
            updated_at=timestamp,
        )
        approved = Reservation(
            college_id=college.id,
            user_id=student.id,
            device_id=device.id,
            purpose="approved request",
            purpose_category="RESEARCH",
            start_date=start + timedelta(days=1),
            end_date=start + timedelta(days=1),
            status="APPROVED",
            created_at=timestamp,
            updated_at=timestamp,
        )
        session.add_all([pending, approved])
        await session.flush()
        session.add(
            ReservationItem(
                reservation_id=pending.id,
                device_id=device.id,
                reservation_date=start,
            )
        )
        session.add(
            RepairReport(
                college_id=college.id,
                device_id=device.id,
                reporter_id=student.id,
                title="open repair blocks returning to idle",
                status="PENDING",
                priority="NORMAL",
            )
        )
        await session.commit()
        unmanaged_device_id = unmanaged_device.id

    async with _client(factory, actor, tmp_path) as client:
        actor["value"] = _principal(manager.id, manager.username, college.id, "LAB_ADMIN")
        denied_delete = await client.delete(f"/api/v2/devices/{device.id}")
        assert denied_delete.status_code == 403
        denied_status = await client.patch(
            f"/api/v2/devices/{device.id}/status", json={"status": "MAINTENANCE"}
        )
        assert denied_status.status_code == 403

        actor["value"] = _manager(manager.id, manager.username, college.id)
        unmanaged_status = await client.patch(
            f"/api/v2/devices/{unmanaged_device_id}/status",
            json={"status": "MAINTENANCE"},
        )
        assert unmanaged_status.status_code == 403
        unmanaged_delete = await client.delete(f"/api/v2/devices/{unmanaged_device_id}")
        assert unmanaged_delete.status_code == 403

        blocked_idle = await client.patch(
            f"/api/v2/devices/{device.id}/status",
            json={"status": "IDLE", "reason": "repair still open"},
        )
        assert blocked_idle.status_code == 409
        assert blocked_idle.json()["code"] == "DEVICE_HAS_OPEN_REPAIR"

        changed = await client.patch(
            f"/api/v2/devices/{device.id}/status",
            json={"status": "MAINTENANCE", "reason": "scheduled maintenance"},
        )
        assert changed.status_code == 200
        assert changed.json()["data"]["status"] == "MAINTENANCE"

        active_delete = await client.delete(f"/api/v2/devices/{device.id}")
        assert active_delete.status_code == 409
        assert active_delete.json()["code"] == "DEVICE_HAS_ACTIVE_RESERVATIONS"

        async with factory() as session:
            pending_row = await session.scalar(
                select(Reservation).where(Reservation.purpose == "pending request")
            )
            approved_row = await session.scalar(
                select(Reservation).where(Reservation.purpose == "approved request")
            )
            assert pending_row.status == "REJECTED"
            assert approved_row.status == "APPROVED"
            assert (
                await session.scalar(
                    select(ReservationItem.id).where(
                        ReservationItem.reservation_id == pending_row.id
                    )
                )
                is None
            )
            tasks = list(
                (
                    await session.scalars(
                        select(OutboxTask).where(OutboxTask.task_type == "NOTIFICATION")
                    )
                ).all()
            )
            assert len(tasks) == 2
            repair = await session.scalar(
                select(RepairReport).where(RepairReport.device_id == device.id)
            )
            repair.status = "CLOSED"
            approved_row.status = "CANCELLED"
            await session.commit()

        restored = await client.patch(
            f"/api/v2/devices/{device.id}/status",
            json={"status": "IDLE", "reason": "repair closed"},
        )
        assert restored.status_code == 200

        deleted = await client.delete(f"/api/v2/devices/{device.id}")
        assert deleted.status_code == 200

    async with factory() as session:
        current = await session.get(Device, device.id)
        assert current.status == "DELETED"
        history = list(
            (
                await session.scalars(
                    select(DeviceStatusHistory).where(DeviceStatusHistory.device_id == device.id)
                )
            ).all()
        )
        assert [item.new_status for item in history] == ["MAINTENANCE", "IDLE", "DELETED"]
