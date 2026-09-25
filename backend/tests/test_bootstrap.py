from datetime import date, datetime, time, timedelta

import pytest
from app.auth.security import verify_password
from app.core.settings import Settings
from app.infrastructure.db.bootstrap import ensure_bootstrap_admin
from app.infrastructure.db.models import DeviceHandover, Reservation, Role, User
from app.infrastructure.db.operational_bootstrap import backfill_unfinished_handovers
from sqlalchemy import func, select


@pytest.mark.asyncio
async def test_bootstrap_admin_is_opt_in_and_idempotent(session_factory) -> None:
    async with session_factory() as session:
        session.add(Role(role_code="SYS_ADMIN", role_name="系统管理员"))
        await session.commit()

    settings = Settings(
        environment="test",
        cors_origins=[],
        enable_workers=False,
        bootstrap_admin_password="strong-admin-password",
    )
    await ensure_bootstrap_admin(session_factory, settings)
    await ensure_bootstrap_admin(session_factory, settings)

    async with session_factory() as session:
        admin = await session.scalar(select(User).where(User.username == "admin"))
        count = int(
            await session.scalar(select(func.count(User.id)).where(User.username == "admin")) or 0
        )

    assert admin is not None
    assert count == 1
    assert verify_password("strong-admin-password", admin.password_hash)


@pytest.mark.asyncio
async def test_unfinished_reservations_are_backfilled_without_fabricating_legacy_handover(
    seeded,
) -> None:
    factory, college, _, student, _, _, device, _ = seeded
    now = datetime.now()
    day = date.today() + timedelta(days=1)
    states = {
        "PENDING": ("PENDING", "NOT_REQUIRED"),
        "APPROVED": ("APPROVED", "PENDING"),
        "IN_USE": ("IN_USE", "NOT_REQUIRED"),
        "RETURN_PENDING": ("IN_USE", "RETURN_PENDING"),
        "EXCEPTION": ("APPROVED", "EXCEPTION"),
    }

    async with factory() as session:
        reservations = [
            Reservation(
                college_id=college.id,
                user_id=student.id,
                device_id=device.id,
                purpose="历史预约规则迁移测试",
                start_date=day,
                end_date=day,
                start_time=datetime.combine(day, time.min),
                end_time=datetime.combine(day, time.max),
                slot_count=1,
                status=status,
                handover_status=handover_status,
                created_at=now,
                updated_at=now,
            )
            for status, handover_status in states.values()
        ]
        session.add_all(reservations)
        await session.flush()
        ids = dict(zip(states, (row.id for row in reservations), strict=True))
        # The previous external-loan bootstrap could mark legacy IN_USE rows
        # HANDED_OVER without recording an operator or an event timestamp.
        session.add(
            DeviceHandover(
                reservation_id=ids["IN_USE"],
                device_id=device.id,
                user_id=student.id,
                college_id=college.id,
                status="HANDED_OVER",
                created_at=now,
                updated_at=now,
            )
        )
        for key, handover_status in (
            ("RETURN_PENDING", "RETURN_PENDING"),
            ("EXCEPTION", "EXCEPTION"),
        ):
            session.add(
                DeviceHandover(
                    reservation_id=ids[key],
                    device_id=device.id,
                    user_id=student.id,
                    college_id=college.id,
                    status=handover_status,
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.flush()

        await backfill_unfinished_handovers(session, now)
        await session.commit()

        handovers = list((await session.scalars(select(DeviceHandover))).all())
        by_reservation = {row.reservation_id: row for row in handovers}
        current_reservations = {
            row.id: row for row in (await session.scalars(select(Reservation))).all()
        }

        assert by_reservation[ids["PENDING"]].status == "PENDING"
        assert by_reservation[ids["APPROVED"]].status == "PENDING"
        legacy_in_use = by_reservation[ids["IN_USE"]]
        assert legacy_in_use.status == "LEGACY_IN_USE"
        assert legacy_in_use.handover_by is None
        assert legacy_in_use.handover_at is None
        assert "未记录交接人和交接时间" in (legacy_in_use.handover_note or "")
        assert by_reservation[ids["RETURN_PENDING"]].status == "RETURN_PENDING"
        assert by_reservation[ids["EXCEPTION"]].status == "EXCEPTION"
        assert current_reservations[ids["RETURN_PENDING"]].status == "IN_USE"
        assert current_reservations[ids["EXCEPTION"]].status == "APPROVED"

        await backfill_unfinished_handovers(session, now)
        await session.commit()
        count = int(await session.scalar(select(func.count(DeviceHandover.id))) or 0)
        assert count == len(states)
