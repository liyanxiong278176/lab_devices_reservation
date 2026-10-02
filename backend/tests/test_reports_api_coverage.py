from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest
from app.auth.csrf import enforce_csrf
from app.auth.security import Principal, get_current_principal
from app.core.settings import Settings
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.db.models import (
    Device,
    DeviceStatusHistory,
    ExportTask,
    OutboxTask,
    Reservation,
    ReservationBlackout,
    ReservationWaitlist,
)
from app.infrastructure.db.session import get_db
from app.main import create_app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
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
        token_id=f"reports-{user_id}",
        permissions=permissions,
    )


@asynccontextmanager
async def _client(
    session_factory: async_sessionmaker[AsyncSession],
    actor: dict[str, Principal],
    upload_dir: Path,
    *,
    export_sync_row_limit: int = 1000,
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
            export_sync_row_limit=export_sync_row_limit,
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
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


def _report_admin(user_id: int, college_id: int | None = None) -> Principal:
    return _principal(
        user_id,
        "report-admin",
        college_id,
        "SYS_ADMIN" if college_id is None else "LAB_ADMIN",
        permissions=("report:read", "device:read"),
    )


@pytest.mark.asyncio
async def test_report_summary_validates_range_and_handles_empty_scope(
    seeded, tmp_path: Path
) -> None:
    factory, _college, _other_college, _student, _other_student, manager, *_ = seeded
    actor = {"value": _report_admin(manager.id)}
    async with _client(factory, actor, tmp_path) as client:
        reversed_range = await client.get(
            "/api/v2/reports/summary",
            params={"start_date": "2026-10-02", "end_date": "2026-10-01"},
        )
        assert reversed_range.status_code == 422
        assert reversed_range.json()["code"] == "DATE_RANGE_INVALID"

        too_wide = await client.get(
            "/api/v2/reports/summary",
            params={"start_date": "2020-01-01", "end_date": date.today().isoformat()},
        )
        assert too_wide.status_code == 422
        assert too_wide.json()["code"] == "DATE_RANGE_TOO_LARGE"

        empty = await client.get(
            "/api/v2/reports/summary",
            params={
                "college_id": 999999,
                "start_date": date.today().isoformat(),
                "end_date": date.today().isoformat(),
            },
        )
        assert empty.status_code == 200
        result = empty.json()["data"]
        assert result["deviceCount"] == 0
        assert result["bookableDeviceDays"] == 0
        assert result["occupancyRate"] == 0
        assert result["waitlistConversionRate"] == 0
        assert result["averageApprovalHours"] == 0


@pytest.mark.asyncio
async def test_report_summary_calculates_state_blackout_occupancy_and_waitlist_metrics(
    seeded, tmp_path: Path
) -> None:
    factory, college, other_college, student, _other_student, manager, device, other_device = seeded
    actor = {"value": _report_admin(manager.id)}
    start = date.today() - timedelta(days=5)
    end = start + timedelta(days=2)
    start_at = datetime.combine(start, time.min)
    async with factory() as session:
        # The first device starts in maintenance, becomes bookable for a day,
        # and then re-enters maintenance. Scope-level blackouts exercise the
        # device, lab, and college checks independently.
        session.add_all(
            [
                DeviceStatusHistory(
                    device_id=device.id,
                    college_id=college.id,
                    old_status="IDLE",
                    new_status="MAINTENANCE",
                    created_at=start_at - timedelta(hours=2),
                ),
                DeviceStatusHistory(
                    device_id=device.id,
                    college_id=college.id,
                    old_status="MAINTENANCE",
                    new_status="IDLE",
                    created_at=start_at + timedelta(hours=2),
                ),
                DeviceStatusHistory(
                    device_id=device.id,
                    college_id=college.id,
                    old_status="IDLE",
                    new_status="MAINTENANCE",
                    created_at=start_at + timedelta(days=1, hours=2),
                ),
                DeviceStatusHistory(
                    device_id=other_device.id,
                    college_id=other_college.id,
                    old_status=None,
                    new_status="IDLE",
                    created_at=start_at + timedelta(hours=1),
                ),
                ReservationBlackout(
                    scope_type="DEVICE",
                    scope_id=device.id,
                    blocked_date=start,
                    reason="device blackout",
                    created_by=manager.id,
                ),
                ReservationBlackout(
                    scope_type="LAB",
                    scope_id=device.lab_id,
                    blocked_date=start + timedelta(days=1),
                    reason="lab blackout",
                    created_by=manager.id,
                ),
                ReservationBlackout(
                    scope_type="COLLEGE",
                    scope_id=college.id,
                    blocked_date=end,
                    reason="college blackout",
                    created_by=manager.id,
                ),
                Reservation(
                    college_id=other_college.id,
                    user_id=student.id,
                    device_id=other_device.id,
                    purpose="usage report test",
                    purpose_category="RESEARCH",
                    start_date=start,
                    end_date=start + timedelta(days=1),
                    status="IN_USE",
                    check_in_at=start_at + timedelta(hours=3),
                    created_at=start_at,
                    updated_at=start_at,
                    approved_at=start_at + timedelta(hours=1),
                ),
                Reservation(
                    college_id=college.id,
                    user_id=student.id,
                    device_id=device.id,
                    purpose="reservation on an unavailable date",
                    purpose_category="RESEARCH",
                    start_date=start,
                    end_date=start,
                    status="APPROVED",
                    created_at=start_at,
                    updated_at=start_at,
                ),
                Reservation(
                    college_id=other_college.id,
                    user_id=student.id,
                    device_id=other_device.id,
                    purpose="approved without check-in data",
                    purpose_category="RESEARCH",
                    start_date=end,
                    end_date=end,
                    status="APPROVED",
                    created_at=start_at,
                    updated_at=start_at,
                ),
                Reservation(
                    college_id=other_college.id,
                    user_id=student.id,
                    device_id=other_device.id,
                    purpose="pending reservation excluded from occupancy",
                    purpose_category="RESEARCH",
                    start_date=end,
                    end_date=end,
                    status="PENDING",
                    created_at=start_at,
                    updated_at=start_at,
                ),
                ReservationWaitlist(
                    device_id=other_device.id,
                    college_id=other_college.id,
                    user_id=student.id,
                    reservation_date=start,
                    purpose="converted waitlist",
                    status="CONFIRMED",
                    created_at=start_at + timedelta(hours=4),
                ),
                ReservationWaitlist(
                    device_id=other_device.id,
                    college_id=other_college.id,
                    user_id=student.id,
                    reservation_date=start + timedelta(days=1),
                    purpose="unconverted waitlist",
                    status="WAITING",
                    created_at=start_at + timedelta(hours=5),
                ),
            ]
        )
        second_device = await session.get(Device, other_device.id)
        second_device.status = "IDLE"
        await session.commit()

    async with _client(factory, actor, tmp_path) as client:
        response = await client.get(
            "/api/v2/reports/summary",
            params={"start_date": start.isoformat(), "end_date": end.isoformat()},
        )
    assert response.status_code == 200
    result = response.json()["data"]
    assert result["deviceCount"] == 2
    assert result["reservationCount"] == 4
    assert result["reservationStatus"] == {"APPROVED": 2, "IN_USE": 1, "PENDING": 1}
    assert result["bookableDeviceDays"] > 0
    assert result["occupiedDeviceDays"] == 3
    assert result["actualUsageDeviceDays"] == 2
    assert result["maintenanceDowntimeDays"] >= 2
    assert result["averageApprovalHours"] == 1
    assert result["waitlistRequests"] == 2
    assert result["waitlistConverted"] == 1
    assert result["waitlistConversionRate"] == 0.5


@pytest.mark.asyncio
async def test_report_summary_handles_devices_without_tenant_or_lab_ids_and_future_state(
    seeded, tmp_path: Path
) -> None:
    factory, _college, _other_college, _student, _other_student, manager, device, other_device = (
        seeded
    )
    actor = {"value": _report_admin(manager.id)}
    start = date.today()
    async with factory() as session:
        first_device = await session.get(Device, device.id)
        second_device = await session.get(Device, other_device.id)
        first_device.college_id = None
        first_device.lab_id = None
        second_device.college_id = None
        second_device.lab_id = None
        session.add(
            DeviceStatusHistory(
                device_id=device.id,
                college_id=None,
                old_status="DISABLED",
                new_status="IDLE",
                created_at=datetime.combine(start + timedelta(days=1), time.min),
            )
        )
        await session.commit()

    async with _client(factory, actor, tmp_path) as client:
        response = await client.get(
            "/api/v2/reports/summary",
            params={"start_date": start.isoformat(), "end_date": start.isoformat()},
        )
    assert response.status_code == 200
    result = response.json()["data"]
    assert result["deviceCount"] == 2
    assert result["bookableDeviceDays"] == 1
    assert result["maintenanceDowntimeDays"] == 0


@pytest.mark.asyncio
async def test_direct_device_export_escapes_spreadsheet_formulas_and_enforces_sync_limit(
    seeded, tmp_path: Path
) -> None:
    factory, college, _other_college, _student, _other_student, manager, device, _other_device = (
        seeded
    )
    async with factory() as session:
        row = await session.get(Device, device.id)
        row.name = '=HYPERLINK("https://example.invalid")'
        await session.commit()
    actor = {"value": _report_admin(manager.id, college.id)}

    async with _client(factory, actor, tmp_path) as client:
        exported = await client.get("/api/v2/reports/export/devices")
        assert exported.status_code == 200
        assert exported.content.startswith(b"\xef\xbb\xbf")
        assert b"'=HYPERLINK" in exported.content
        assert "lab-devices.csv" in exported.headers["content-disposition"]

        empty = await client.get("/api/v2/reports/export/devices", params={"status": "UNKNOWN"})
        assert empty.status_code == 200
        assert "暂无数据" in empty.content.decode("utf-8-sig")

    async with _client(factory, actor, tmp_path, export_sync_row_limit=0) as limited_client:
        too_many = await limited_client.get("/api/v2/reports/export/devices")
    assert too_many.status_code == 413
    assert too_many.json()["code"] == "EXPORT_ASYNC_REQUIRED"


@pytest.mark.asyncio
async def test_async_export_permissions_scope_status_and_safe_download(
    seeded, tmp_path: Path
) -> None:
    factory, college, _other_college, student, other_student, manager, device, _other_device = (
        seeded
    )
    manager_actor = {"value": _report_admin(manager.id, college.id)}
    student_actor = {"value": _principal(student.id, student.username, college.id, "STUDENT")}

    async with _client(factory, student_actor, tmp_path) as client:
        forbidden = await client.post("/api/v2/reports/exports", json={"export_type": "devices"})
        assert forbidden.status_code == 403

    async with _client(factory, manager_actor, tmp_path) as client:
        invalid_range = await client.post(
            "/api/v2/reports/exports",
            json={"export_type": "devices", "start_date": "2026-10-02", "end_date": "2026-10-01"},
        )
        assert invalid_range.status_code == 422
        assert invalid_range.json()["code"] == "DATE_RANGE_INVALID"

        created = await client.post(
            "/api/v2/reports/exports",
            json={"export_type": "devices", "college_id": college.id},
        )
        assert created.status_code == 202
        task = created.json()["data"]
        task_id = task["id"]
        assert task["status"] == "PENDING"
        assert task["download_url"] is None

        pending_download = await client.get(f"/api/v2/reports/exports/{task_id}/download")
        assert pending_download.status_code == 409
        assert pending_download.json()["code"] == "EXPORT_NOT_READY"

        actor_original = manager_actor["value"]
        manager_actor["value"] = _principal(
            other_student.id,
            other_student.username,
            college.id,
            "LAB_ADMIN",
            permissions=("report:read",),
        )
        hidden = await client.get(f"/api/v2/reports/exports/{task_id}")
        assert hidden.status_code == 404
        manager_actor["value"] = actor_original

        missing = await client.get("/api/v2/reports/exports/999999")
        assert missing.status_code == 404

        manager_principal = manager_actor["value"]
        manager_actor["value"] = _report_admin(manager.id)
        global_admin_status = await client.get(f"/api/v2/reports/exports/{task_id}")
        assert global_admin_status.status_code == 200
        manager_actor["value"] = manager_principal

        async with factory() as session:
            row = await session.get(ExportTask, task_id)
            row.status = "COMPLETED"
            row.file_token = "completed-export"
            row.file_path = str(tmp_path / "export.csv")
            row.row_count = 1
            await session.commit()
        (tmp_path / "export.csv").write_bytes(b"device-id\r\n1\r\n")

        status = await client.get(f"/api/v2/reports/exports/{task_id}")
        assert status.status_code == 200
        assert status.json()["data"]["download_url"].endswith(
            f"/reports/exports/{task_id}/download"
        )
        downloaded = await client.get(f"/api/v2/reports/exports/{task_id}/download")
        assert downloaded.status_code == 200
        assert downloaded.content == b"device-id\r\n1\r\n"

        async with factory() as session:
            row = await session.get(ExportTask, task_id)
            row.file_path = str(tmp_path.parent / "outside.csv")
            await session.commit()
        escaped_path = await client.get(f"/api/v2/reports/exports/{task_id}/download")
        assert escaped_path.status_code == 404

        async with factory() as session:
            row = await session.get(ExportTask, task_id)
            row.file_path = str(tmp_path / "missing.csv")
            await session.commit()
        missing_file = await client.get(f"/api/v2/reports/exports/{task_id}/download")
        assert missing_file.status_code == 404

        async with factory() as session:
            current_device = await session.get(Device, device.id)
            original_lab_id = current_device.lab_id
            current_device.lab_id = None
            await session.commit()
        changed_scope = await client.get(f"/api/v2/reports/exports/{task_id}")
        assert changed_scope.status_code == 404
        async with factory() as session:
            current_device = await session.get(Device, device.id)
            current_device.lab_id = original_lab_id
            await session.commit()

    async with factory() as session:
        tasks = list((await session.scalars(select(ExportTask))).all())
        assert len(tasks) == 1
        outbox = await session.scalar(
            select(OutboxTask).where(OutboxTask.task_key == f"export:{tasks[0].id}:generate")
        )
        assert outbox is not None

        unscoped_task = ExportTask(
            requester_id=manager.id,
            college_id=college.id,
            export_type="devices",
            filters=None,
            status="PENDING",
        )
        session.add(unscoped_task)
        await session.commit()
        unscoped_task_id = unscoped_task.id

    async with _client(factory, manager_actor, tmp_path) as client:
        unscoped_status = await client.get(f"/api/v2/reports/exports/{unscoped_task_id}")
    assert unscoped_status.status_code == 200
