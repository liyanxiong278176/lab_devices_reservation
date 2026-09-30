from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from app.application.exports import (
    _serial,
    csv_chunk_text,
    export_rows,
    managed_device_ids,
    safe_csv_row,
    scope_fingerprint,
)
from app.auth.security import Principal
from app.core.errors import ApiError
from app.infrastructure.db.models import Device, Lab, RepairReport, Reservation, User
from sqlalchemy import update


def principal(user, college_id: int | None, role: str) -> Principal:
    return Principal(
        user_id=user.id,
        username=user.username,
        college_id=college_id,
        roles=(role,),
        token_type="access",
        token_id=f"export-{role.lower()}",
    )


def test_export_scalar_and_csv_helpers_cover_dates_headers_and_formulas() -> None:
    assert _serial(date(2026, 9, 28)) == "2026-09-28"
    assert _serial(datetime(2026, 9, 28, 9, 30)) == "2026-09-28 09:30:00"
    assert _serial(7) == 7
    assert scope_fingerprint([3, 1, 2], 9) == scope_fingerprint([2, 3, 1], 9)
    assert scope_fingerprint(None, None) != scope_fingerprint([], None)
    assert safe_csv_row({"leading-control": "\x00-2", "plain": None}) == {
        "leading-control": "'\x00-2",
        "plain": None,
    }

    with_header = csv_chunk_text(
        [{"name": "=1+1", "extra": "ignored"}], ["name"], include_header=True
    )
    without_header = csv_chunk_text([{"name": "safe"}], ["name"])
    assert with_header.splitlines() == ["name", "'=1+1"]
    assert without_header == "safe\r\n"


@pytest.mark.asyncio
async def test_export_scope_authorization_and_admin_scope_variants(seeded) -> None:
    factory, college, _, _, _, manager, device, _ = seeded
    async with factory() as session:
        manager_scope = principal(manager, college.id, "LAB_ADMIN")
        ids, scope = await managed_device_ids(session, manager_scope)
        assert ids == [device.id]
        assert scope == college.id

        with pytest.raises(ApiError) as out_of_scope:
            await managed_device_ids(session, manager_scope, college_id=college.id + 1)
        assert out_of_scope.value.code == "FORBIDDEN"

        with pytest.raises(ApiError) as student_denied:
            await managed_device_ids(session, principal(manager, college.id, "STUDENT"))
        assert student_denied.value.code == "FORBIDDEN"

        system_admin = principal(manager, college.id, "SYS_ADMIN")
        all_ids, all_scope = await managed_device_ids(session, system_admin)
        assert all_ids is None
        assert all_scope is None
        scoped_ids, scoped_scope = await managed_device_ids(
            session,
            system_admin,
            college_id=college.id,
        )
        assert scoped_ids == [device.id]
        assert scoped_scope == college.id


@pytest.mark.asyncio
async def test_device_export_serializes_optional_fields_and_filters(seeded) -> None:
    factory, college, _, _, _, manager, device, _ = seeded
    async with factory() as session:
        stored_device = await session.get(Device, device.id)
        assert stored_device is not None
        stored_device.asset_code = "EQ-10"
        stored_device.serial_number = "SER-10"
        stored_device.brand = "Maker"
        stored_device.model = "M1"
        stored_device.risk_level = "HIGH"
        stored_device.allow_external_loan = True
        stored_device.purchase_date = date(2024, 1, 2)
        stored_device.warranty_until = None
        stored_device.status = "IDLE"
        await session.commit()

    async with factory() as session:
        rows = await export_rows(
            session,
            principal(manager, college.id, "LAB_ADMIN"),
            "devices",
            {"status": "IDLE"},
        )
        assert len(rows) == 1
        assert rows[0]["设备名称"] == "GPU 工作站"
        assert rows[0]["资产编号"] == "EQ-10"
        assert rows[0]["允许外借"] == "是"
        assert rows[0]["购置日期"] == "2024-01-02"
        assert rows[0]["保修截止"] is None

        no_matches = await export_rows(
            session,
            principal(manager, college.id, "LAB_ADMIN"),
            "devices",
            {"status": "RETIRED"},
        )
        assert no_matches == []

        global_rows = await export_rows(
            session,
            principal(manager, college.id, "SYS_ADMIN"),
            "devices",
        )
        assert any(row["设备ID"] == device.id for row in global_rows)


@pytest.mark.asyncio
async def test_reservation_export_includes_user_fallback_and_date_filters(seeded) -> None:
    factory, college, _, student, _, manager, device, _ = seeded
    start = date(2026, 9, 28)
    async with factory() as session:
        session.add(
            Reservation(
                college_id=college.id,
                user_id=student.id,
                device_id=device.id,
                purpose="课程实验",
                purpose_category="COURSE",
                project_reference="BIO-1",
                start_date=start,
                end_date=start + timedelta(days=1),
                status="APPROVED",
            )
        )
        await session.commit()

    async with factory() as session:
        rows = await export_rows(
            session,
            principal(manager, college.id, "LAB_ADMIN"),
            "reservations",
            {"start_date": "2026-09-29", "end_date": "2026-09-30", "status": "APPROVED"},
        )
        assert len(rows) == 1
        assert rows[0]["预约人"] == "学生一"
        assert rows[0]["用途类别"] == "COURSE"
        assert rows[0]["开始日期"] == "2026-09-28"
        assert rows[0]["课程或项目"] == "BIO-1"

        with pytest.raises(ApiError) as invalid_range:
            await export_rows(
                session,
                principal(manager, college.id, "LAB_ADMIN"),
                "reservations",
                {"start_date": "2026-10-01", "end_date": "2026-09-30"},
            )
        assert invalid_range.value.code == "DATE_RANGE_INVALID"

    async with factory() as session:
        stored_student = await session.get(User, student.id)
        assert stored_student is not None
        stored_student.real_name = None
        await session.commit()

    async with factory() as session:
        unfiltered = await export_rows(
            session,
            principal(manager, college.id, "LAB_ADMIN"),
            "reservations",
            max_rows=10,
        )
        assert unfiltered[0]["预约人"] == student.username


@pytest.mark.asyncio
async def test_repair_export_formats_elapsed_days_and_empty_manager_scope(seeded) -> None:
    factory, college, _, reporter, second_reporter, manager, device, _ = seeded
    created = datetime(2026, 9, 20, 9)
    async with factory() as session:
        session.add(
            RepairReport(
                college_id=college.id,
                device_id=device.id,
                reporter_id=reporter.id,
                title="电源异常",
                priority="URGENT",
                status="CLOSED",
                created_at=created,
                taken_at=created + timedelta(hours=2),
                resolved_at=created + timedelta(days=1),
                closed_at=created + timedelta(days=2),
            )
        )
        second_user = await session.get(User, second_reporter.id)
        assert second_user is not None
        second_user.real_name = None
        session.add(
            RepairReport(
                college_id=college.id,
                device_id=device.id,
                reporter_id=second_reporter.id,
                title="待受理报修",
                priority="NORMAL",
                status="PENDING",
                created_at=created + timedelta(hours=1),
            )
        )
        await session.commit()

    async with factory() as session:
        rows = await export_rows(
            session,
            principal(manager, college.id, "LAB_ADMIN"),
            "repairs",
            {"start_date": "2026-09-20", "end_date": "2026-09-21", "status": "CLOSED"},
        )
        assert len(rows) == 1
        assert rows[0]["报修人"] == "学生一"
        assert rows[0]["处理时长(天)"] == 2

        null_duration = await export_rows(
            session,
            principal(manager, college.id, "LAB_ADMIN"),
            "repairs",
            max_rows=10,
        )
        assert len(null_duration) == 2
        pending = next(row for row in null_duration if row["状态"] == "PENDING")
        assert pending["处理时长(天)"] is None
        assert pending["报修人"] == second_reporter.username

        with pytest.raises(ApiError) as invalid_kind:
            await export_rows(
                session,
                principal(manager, college.id, "LAB_ADMIN"),
                "unknown",  # type: ignore[arg-type]
            )
        assert invalid_kind.value.code == "EXPORT_TYPE_INVALID"

    async with factory() as session:
        await session.execute(update(Lab).where(Lab.id == device.lab_id).values(manager_id=None))
        await session.commit()
        empty_ids, _ = await managed_device_ids(
            session,
            principal(manager, college.id, "LAB_ADMIN"),
        )
        assert empty_ids == []
        assert await export_rows(
            session,
            principal(manager, college.id, "LAB_ADMIN"),
            "reservations",
        ) == []
        assert await export_rows(
            session,
            principal(manager, college.id, "LAB_ADMIN"),
            "devices",
        ) == []
