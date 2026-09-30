"""MySQL-only concurrency coverage for the reservation handover CAS."""

from __future__ import annotations

import asyncio
import os
import secrets
from datetime import date

import pytest
from app.api.v2.schemas import ReservationPlanRequest
from app.application.reservations import ReservationService
from app.auth.security import Principal
from app.core.errors import ApiError
from app.core.settings import Settings
from app.core.uploads import _upload_is_referenced
from app.infrastructure.db.models import (
    Device,
    DeviceHandover,
    RepairReport,
    Reservation,
    UploadAsset,
    User,
)
from app.infrastructure.db.session import build_engine, build_session_factory
from scripts.e2e_fixture import cleanup, seed
from sqlalchemy import func, select


def _principal(user: User, role: str) -> Principal:
    permissions = (
        ("reservation:create", "reservation:read:own")
        if role == "STUDENT"
        else (
            "reservation:read:scope",
            "reservation:approve",
            "reservation:handover",
            "reservation:accept-return",
        )
    )
    return Principal(
        user_id=user.id,
        username=user.username,
        college_id=user.college_id,
        roles=(role,),
        token_type="access",
        token_id="mysql-handover-race-test",
        permissions=permissions,
    )


@pytest.mark.asyncio
async def test_mysql_serializes_normal_and_exception_handover_updates() -> None:
    if os.getenv("LAB_RUN_MYSQL_INTEGRATION") != "1":
        pytest.skip("set LAB_RUN_MYSQL_INTEGRATION=1 to run against the configured MySQL")

    settings = Settings()
    if settings.mysql_dsn.startswith("sqlite"):
        pytest.skip("this test verifies MySQL row-lock and affected-row semantics")

    prefix = f"e2e-mysql-race-{secrets.token_hex(4)}"
    engine = None
    try:
        await seed(prefix)
        engine = build_engine(settings)
        factory = build_session_factory(engine)
        async with factory() as session:
            student = await session.scalar(select(User).where(User.username == f"{prefix}-user"))
            manager = await session.scalar(select(User).where(User.username == f"{prefix}-manager"))
            device = await session.scalar(select(Device).where(Device.name == f"{prefix}-device"))
            assert student is not None and manager is not None and device is not None
            created = await ReservationService(
                session,
                _principal(student, "STUDENT"),
            ).create(
                ReservationPlanRequest(
                    device_id=device.id,
                    start_date=date.today(),
                    end_date=date.today(),
                    purpose="MySQL 并发交接条件更新验证",
                )
            )
            reservation_id = created.created[0].id
            approved = await ReservationService(
                session,
                _principal(manager, "LAB_ADMIN"),
            ).approve(reservation_id, True)
            assert approved.status == "APPROVED"

            college_id = manager.college_id
            image_urls = [
                f"/api/v2/repair-uploads/mysql-race-normal-{secrets.token_hex(8)}",
                f"/api/v2/repair-uploads/mysql-race-exception-{secrets.token_hex(8)}",
            ]
            session.add_all(
                [
                    UploadAsset(
                        asset_token=url.rsplit("/", 1)[-1],
                        user_id=manager.id,
                        college_id=college_id,
                        original_name="race-evidence.png",
                        content_type="image/png",
                        size_bytes=128,
                        storage_path=f"memory://{url.rsplit('/', 1)[-1]}",
                    )
                    for url in image_urls
                ]
            )
            await session.commit()

        barrier = asyncio.Barrier(2)

        async def submit_handover(condition: str, image_url: str):
            async with factory() as session:
                service = ReservationService(session, _principal(manager, "LAB_ADMIN"))
                load_reservation = service._load_reservation

                async def load_then_wait(current_reservation_id: int):
                    reservation = await load_reservation(current_reservation_id)
                    await barrier.wait()
                    return reservation

                service._load_reservation = load_then_wait  # type: ignore[method-assign]
                return await service.handover(
                    reservation_id,
                    condition=condition,
                    note="并发交接竞争测试",
                    image_urls=[image_url],
                    checklist=[{"name": "电源线", "condition": "NORMAL"}],
                )

        outcomes = await asyncio.gather(
            submit_handover("NORMAL", image_urls[0]),
            submit_handover("DAMAGED", image_urls[1]),
            return_exceptions=True,
        )
        successes = [result for result in outcomes if not isinstance(result, BaseException)]
        failures = [result for result in outcomes if isinstance(result, BaseException)]
        assert len(successes) == 1, outcomes
        assert len(failures) == 1 and isinstance(failures[0], ApiError), outcomes
        assert failures[0].status_code == 409

        async with factory() as session:
            reservation = await session.get(Reservation, reservation_id)
            handover = await session.scalar(
                select(DeviceHandover).where(DeviceHandover.reservation_id == reservation_id)
            )
            repair_count = int(
                await session.scalar(
                    select(func.count(RepairReport.id)).where(
                        RepairReport.reservation_id == reservation_id
                    )
                )
                or 0
            )
            assert reservation is not None and handover is not None
            if reservation.status == "IN_USE":
                assert reservation.handover_status == handover.status == "HANDED_OVER"
                assert repair_count == 0
            else:
                assert reservation.status == "APPROVED"
                assert reservation.handover_status == handover.status == "EXCEPTION"
                assert repair_count == 1

            evidence_url = handover.handover_image_urls[0]
            evidence_token = evidence_url.rsplit("/", 1)[-1]
            evidence_asset = await session.scalar(
                select(UploadAsset).where(UploadAsset.asset_token == evidence_token)
            )
            assert evidence_asset is not None
            assert await session.scalar(
                select(
                    _upload_is_referenced(
                        evidence_asset.id,
                        evidence_asset.asset_token,
                        mysql=True,
                    )
                )
            )
    finally:
        if engine is not None:
            await engine.dispose()
        await cleanup(prefix)
