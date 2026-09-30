from __future__ import annotations

import os
import secrets
from datetime import date, timedelta

import pytest
from app.api.v2.schemas import ReservationPlanRequest
from app.application.reservations import ReservationService
from app.auth.security import Principal
from app.core.settings import Settings
from app.infrastructure.db.models import Device, User
from app.infrastructure.db.session import build_engine, build_session_factory
from scripts.e2e_fixture import cleanup, seed
from sqlalchemy import select


@pytest.mark.asyncio
async def test_mysql_delayed_pagination_supports_direct_jumps() -> None:
    if os.getenv("LAB_RUN_MYSQL_INTEGRATION") != "1":
        pytest.skip("set LAB_RUN_MYSQL_INTEGRATION=1 to run against the configured MySQL")

    settings = Settings()
    if settings.mysql_dsn.startswith("sqlite"):
        pytest.skip("this test verifies the MySQL delayed-association query path")

    prefix = f"e2e-pages-{secrets.token_hex(4)}"
    engine = None
    seeded = False
    try:
        await seed(prefix)
        seeded = True
        engine = build_engine(settings)
        factory = build_session_factory(engine)

        async with factory() as session:
            student = await session.scalar(select(User).where(User.username == f"{prefix}-user"))
            manager = await session.scalar(select(User).where(User.username == f"{prefix}-manager"))
            device = await session.scalar(select(Device).where(Device.name == f"{prefix}-device"))
            assert student is not None and manager is not None and device is not None
            student_principal = Principal(
                user_id=student.id,
                username=student.username,
                college_id=student.college_id,
                roles=("STUDENT",),
                token_type="access",
                token_id="mysql-page-student",
                permissions=("reservation:create", "reservation:read:own", "device:read"),
            )
            manager_principal = Principal(
                user_id=manager.id,
                username=manager.username,
                college_id=manager.college_id,
                roles=("LAB_ADMIN",),
                token_type="access",
                token_id="mysql-page-manager",
                permissions=("reservation:read:scope", "reservation:approve"),
            )
            first_day = date.today() + timedelta(days=10)
            reservation_service = ReservationService(session, student_principal)
            for offset in range(3):
                await reservation_service.create(
                    ReservationPlanRequest(
                        device_id=device.id,
                        start_date=first_day + timedelta(days=offset),
                        end_date=first_day + timedelta(days=offset),
                        purpose=f"MySQL direct page {offset}",
                    ),
                    idempotency_key=f"{prefix}-reservation-{offset}",
                )

        async with factory() as session:
            mine = await ReservationService(session, student_principal).list_mine(
                page=3,
                page_size=1,
            )
            approvals = await ReservationService(session, manager_principal).pending_approvals(
                page=2,
                page_size=1,
            )
            devices, total, pages, truncated = await ReservationService(
                session,
                student_principal,
            ).list_devices(page=2, page_size=1, include_meta=True)

        assert mine.total == 3 and mine.page == 3 and len(mine.items) == 1
        assert approvals.total == 3 and approvals.page == 2 and len(approvals.items) == 1
        assert total == 2 and pages == 2 and truncated is False and len(devices) == 1
    finally:
        if engine is not None:
            await engine.dispose()
        if seeded:
            await cleanup(prefix)
