"""MySQL-only verification of the final reservation overbooking guard."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from app.api.v2.devices import _sync_device_reservation_rule
from app.api.v2.schemas import (
    MaintenancePlanWrite,
    MaintenanceRecordCreate,
    ReservationPlanRequest,
)
from app.application.maintenance import MaintenanceService
from app.application.reservations import ReservationService
from app.auth.security import Principal
from app.core.errors import ApiError
from app.core.settings import Settings
from app.core.uploads import cleanup_orphan_uploads
from app.infrastructure.cache.redis import (
    dispose_app_redis,
    get_redis_circuit,
    get_redis_for_app,
)
from app.infrastructure.cache.reservation_quota import ReservationQuotaCache
from app.infrastructure.db.models import (
    Device,
    DeviceMaintenancePlan,
    DeviceMaintenanceRecord,
    DevicePool,
    OutboxTask,
    Reservation,
    ReservationItem,
    ReservationRule,
    Role,
    UploadAsset,
    User,
)
from app.infrastructure.db.session import build_engine, build_session_factory
from app.infrastructure.tasks.worker import OutboxWorker
from app.main import create_app
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from scripts.e2e_fixture import cleanup, seed
from sqlalchemy import func, select


def _reservation_quota_for_settings(settings: Settings):
    app = create_app(settings.model_copy(update={"enable_workers": False}))
    quota_cache = ReservationQuotaCache(
        get_redis_for_app(app),
        get_redis_circuit(app),
    )
    return app, quota_cache


@pytest.mark.asyncio
async def test_mysql_same_device_day_concurrent_booking_has_one_winner(capsys) -> None:
    if os.getenv("LAB_RUN_MYSQL_INTEGRATION") != "1":
        pytest.skip("set LAB_RUN_MYSQL_INTEGRATION=1 to run against the configured MySQL")

    settings = Settings()
    if settings.mysql_dsn.startswith("sqlite"):
        pytest.skip("this test verifies MySQL row-lock and unique-index semantics")

    prefix = f"e2e-reservation-race-{secrets.token_hex(4)}"
    engine = None
    try:
        await seed(prefix)
        capsys.readouterr()
        engine = build_engine(settings)
        factory = build_session_factory(engine)
        async with factory() as session:
            student = await session.scalar(select(User).where(User.username == f"{prefix}-user"))
            student_role = await session.scalar(
                select(Role).where(Role.role_code == "STUDENT")
            )
            device = await session.scalar(select(Device).where(Device.name == f"{prefix}-device"))
            assert student is not None and student_role is not None and device is not None
            users = [student]
            for index in range(1, 8):
                contender = User(
                    username=f"{prefix}-user-{index}",
                    password_hash=student.password_hash,
                    real_name=f"同设备并发用户 {index}",
                    user_type="STUDENT",
                    college_id=student.college_id,
                    status=1,
                    roles=[student_role],
                )
                users.append(contender)
            session.add_all(users[1:])
            await session.flush()
            principals = [
                Principal(
                    user_id=user.id,
                    username=user.username,
                    college_id=user.college_id,
                    roles=("STUDENT",),
                    token_type="access",
                    token_id=f"mysql-reservation-race-{index}-{secrets.token_hex(4)}",
                    permissions=("reservation:create",),
                )
                for index, user in enumerate(users)
            ]
            device_id = device.id
            await session.commit()

        target_date = date.today() + timedelta(days=10)

        async def submit(contender: int):
            async with factory() as session:
                service = ReservationService(session, principals[contender])
                return await service.create(
                    ReservationPlanRequest(
                        device_id=device_id,
                        start_date=target_date,
                        end_date=target_date,
                        purpose=f"同日预约并发竞争 {contender}",
                    ),
                    idempotency_key=f"{prefix}-request-{contender}",
                )

        outcomes = await asyncio.gather(
            *(submit(contender) for contender in range(8)),
            return_exceptions=True,
        )
        successes = [outcome for outcome in outcomes if not isinstance(outcome, BaseException)]
        failures = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
        failure_summary = Counter(
            f"{type(error).__name__}:{getattr(error, 'status_code', 'no-status')}"
            for error in failures
        )

        assert len(successes) == 1, (
            f"expected one winner; got {len(successes)}, errors={dict(failure_summary)}"
        )
        assert len(failures) == 7, (
            f"expected 7 conflicts; got {len(failures)}, errors={dict(failure_summary)}"
        )
        assert all(
            isinstance(error, ApiError) and error.status_code == 409 for error in failures
        ), f"non-conflict failures: {dict(failure_summary)}"

        async with factory() as session:
            occupied_rows = int(
                await session.scalar(
                    select(func.count(ReservationItem.id)).where(
                        ReservationItem.device_id == device_id,
                        ReservationItem.reservation_date == target_date,
                    )
                )
                or 0
            )
            assert occupied_rows == 1
    finally:
        if engine is not None:
            await engine.dispose()
        await cleanup(prefix)


@pytest.mark.asyncio
async def test_mysql_same_user_can_repeat_pool_bookings_until_quota_is_full_and_cancel_releases_it(
    capsys,
) -> None:
    if os.getenv("LAB_RUN_MYSQL_INTEGRATION") != "1":
        pytest.skip("set LAB_RUN_MYSQL_INTEGRATION=1 to run against the configured MySQL")

    settings = Settings()
    if settings.mysql_dsn.startswith("sqlite"):
        pytest.skip("this test verifies MySQL user-row lock semantics across requests")

    prefix = f"e2e-user-pool-repeat-{secrets.token_hex(4)}"
    engine = None
    quota_app = None
    try:
        await seed(prefix, pool_units=2)
        capsys.readouterr()
        engine = build_engine(settings)
        factory = build_session_factory(engine)
        quota_app, quota_cache = _reservation_quota_for_settings(settings)
        assert await quota_cache.redis.ping() is True
        async with factory() as session:
            student = await session.scalar(select(User).where(User.username == f"{prefix}-user"))
            device = await session.scalar(select(Device).where(Device.name == f"{prefix}-device"))
            assert student is not None and device is not None and device.pool_id is not None
            principal = Principal(
                user_id=student.id,
                username=student.username,
                college_id=student.college_id,
                roles=("STUDENT",),
                token_type="access",
                token_id=f"mysql-user-pool-duplicate-{secrets.token_hex(6)}",
                permissions=(
                    "reservation:create",
                    "reservation:cancel",
                    "reservation:read:own",
                ),
            )
            pool_id = device.pool_id
            physical_device_ids = list(
                (
                    await session.scalars(
                        select(Device.id)
                        .where(Device.pool_id == pool_id)
                        .order_by(Device.id)
                    )
                ).all()
            )
            assert len(physical_device_ids) == 2
            target_date = date.today() + timedelta(days=10)
            quota_key = quota_cache._quota_key(pool_id, target_date)
            plan = ReservationPlanRequest(
                pool_id=pool_id,
                start_date=target_date,
                end_date=target_date,
                purpose="同用户资源池重复预约并发验证",
            )
            await session.commit()

        async with factory() as session:
            preflight = await ReservationService(
                session,
                principal,
                reservation_quota=quota_cache,
            ).preflight(plan)
            assert preflight.all_available is True
        assert await quota_cache.redis.hgetall(quota_key) == {
            str(device_id): "1" for device_id in physical_device_ids
        }

        async def submit(key: str):
            async with factory() as session:
                return await ReservationService(
                    session,
                    principal,
                    reservation_quota=quota_cache,
                ).create(
                    plan,
                    idempotency_key=key,
                )

        async def submit_quantity(key: str, quantity: int):
            async with factory() as session:
                return await ReservationService(
                    session,
                    principal,
                    reservation_quota=quota_cache,
                ).create(
                    plan.model_copy(update={"quantity": quantity}),
                    idempotency_key=key,
                )

        replay_key = f"{prefix}-identical-request"
        replay_outcomes = await asyncio.gather(
            submit(replay_key),
            submit(replay_key),
            return_exceptions=True,
        )
        assert all(
            not isinstance(outcome, BaseException) for outcome in replay_outcomes
        ), replay_outcomes
        replay_ids = {outcome.created[0].id for outcome in replay_outcomes}
        assert len(replay_ids) == 1
        reservation_id = replay_ids.pop()
        async with factory() as session:
            initial_reservation = await session.get(Reservation, reservation_id)
            assert initial_reservation is not None
            initial_device_id = initial_reservation.device_id
        initial_hash = await quota_cache.redis.hgetall(quota_key)
        assert initial_hash[str(initial_device_id)] == "0"
        assert sum(value == "1" for value in initial_hash.values()) == 1

        keys = [f"{prefix}-same-user-{index}" for index in range(2)]
        outcomes = await asyncio.gather(
            *(submit(key) for key in keys),
            return_exceptions=True,
        )
        failures = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
        successes = [outcome for outcome in outcomes if not isinstance(outcome, BaseException)]
        assert len(successes) == 1, outcomes
        assert len(failures) == 1, outcomes
        assert all(
            isinstance(error, ApiError)
            and error.status_code == 409
            and error.code in {"RESERVATION_CONFLICT", "RESERVATION_QUOTA_INSUFFICIENT"}
            for error in failures
        ), failures
        assert await quota_cache.redis.hgetall(quota_key) == {
            str(device_id): "0" for device_id in physical_device_ids
        }
        repeated_reservation_id = successes[0].created[0].id
        assert repeated_reservation_id != reservation_id

        # The same user may hold a second, distinct booking while a physical
        # unit remains, but a further request must fail once the pool is full.
        with pytest.raises(ApiError) as exhausted:
            await submit(f"{prefix}-after-quota-exhausted")
        assert exhausted.value.status_code == 409
        assert exhausted.value.code in {
            "RESERVATION_CONFLICT",
            "RESERVATION_QUOTA_INSUFFICIENT",
        }
        assert await quota_cache.redis.hgetall(quota_key) == {
            str(device_id): "0" for device_id in physical_device_ids
        }

        replay = await submit(replay_key)
        assert replay.created[0].id == reservation_id

        async with factory() as session:
            reservation = await session.get(Reservation, reservation_id)
            assert reservation is not None
            await ReservationService(
                session,
                principal,
                reservation_quota=quota_cache,
            ).cancel(reservation_id)
        released_hash = await quota_cache.redis.hgetall(quota_key)
        assert released_hash[str(initial_device_id)] == "1"
        assert sum(value == "1" for value in released_hash.values()) == 1

        # Cancellation frees exactly one unit. A two-unit request must fail
        # atomically and leave the remaining one-unit capacity untouched.
        with pytest.raises(ApiError) as insufficient:
            await submit_quantity(f"{prefix}-insufficient-two-unit-request", 2)
        assert insufficient.value.status_code == 409
        assert insufficient.value.code in {
            "RESERVATION_CONFLICT",
            "RESERVATION_QUOTA_INSUFFICIENT",
        }
        assert await quota_cache.redis.hgetall(quota_key) == released_hash

        async with factory() as session:
            active_rows_before_rebook = int(
                await session.scalar(
                    select(func.count(ReservationItem.id))
                    .join(Reservation, Reservation.id == ReservationItem.reservation_id)
                    .where(
                        Reservation.user_id == student.id,
                        Reservation.status.in_(("PENDING", "APPROVED", "IN_USE")),
                        ReservationItem.reservation_date == target_date,
                        Reservation.device_id.in_(
                            select(Device.id).where(Device.pool_id == pool_id)
                        ),
                    )
                )
                or 0
            )
            assert active_rows_before_rebook == 1

        rebooked = await submit(f"{prefix}-after-cancel")
        assert len(rebooked.created) == 1
        assert rebooked.created[0].id != reservation_id
        assert await quota_cache.redis.hgetall(quota_key) == {
            str(device_id): "0" for device_id in physical_device_ids
        }

        async with factory() as session:
            active_rows = int(
                await session.scalar(
                    select(func.count(ReservationItem.id))
                    .join(Reservation, Reservation.id == ReservationItem.reservation_id)
                    .where(
                        Reservation.user_id == student.id,
                        Reservation.status.in_(("PENDING", "APPROVED", "IN_USE")),
                        ReservationItem.reservation_date == target_date,
                        Reservation.device_id.in_(
                            select(Device.id).where(Device.pool_id == pool_id)
                        ),
                    )
                )
                or 0
            )
            assert active_rows == 2
    finally:
        if quota_app is not None:
            await dispose_app_redis(quota_app)
        if engine is not None:
            await engine.dispose()
        await cleanup(prefix)


@pytest.mark.asyncio
async def test_mysql_multiday_pool_booking_requires_same_physical_device_for_every_day(
    capsys,
) -> None:
    if os.getenv("LAB_RUN_MYSQL_INTEGRATION") != "1":
        pytest.skip("set LAB_RUN_MYSQL_INTEGRATION=1 to run against the configured MySQL")

    settings = Settings()
    if settings.mysql_dsn.startswith("sqlite"):
        pytest.skip("this test verifies MySQL and Redis device-day allocation semantics")

    prefix = f"e2e-pool-continuity-{secrets.token_hex(4)}"
    engine = None
    quota_app = None
    try:
        await seed(prefix, pool_units=2)
        capsys.readouterr()
        engine = build_engine(settings)
        factory = build_session_factory(engine)
        quota_app, quota_cache = _reservation_quota_for_settings(settings)
        assert await quota_cache.redis.ping() is True

        async with factory() as session:
            student = await session.scalar(select(User).where(User.username == f"{prefix}-user"))
            device = await session.scalar(select(Device).where(Device.name == f"{prefix}-device"))
            assert student is not None and device is not None and device.pool_id is not None
            device_ids = list(
                (
                    await session.scalars(
                        select(Device.id)
                        .where(Device.pool_id == device.pool_id)
                        .order_by(Device.id)
                    )
                ).all()
            )
            assert len(device_ids) == 2
            principal = Principal(
                user_id=student.id,
                username=student.username,
                college_id=student.college_id,
                roles=("STUDENT",),
                token_type="access",
                token_id=f"mysql-pool-continuity-{secrets.token_hex(6)}",
                permissions=("reservation:create",),
            )
            pool_id = int(device.pool_id)
            first_day = date.today() + timedelta(days=10)
            second_day = first_day + timedelta(days=1)
            continuous_plan = ReservationPlanRequest(
                pool_id=pool_id,
                start_date=first_day,
                end_date=second_day,
                purpose="验证跨日必须由同一实物设备覆盖",
            )
            await session.commit()

        async with factory() as session:
            preflight = await ReservationService(
                session,
                principal,
                reservation_quota=quota_cache,
            ).preflight(continuous_plan)
            assert preflight.all_available is True

        for current_day, device_id in zip((first_day, second_day), device_ids, strict=True):
            async with factory() as session:
                await ReservationService(
                    session,
                    principal,
                    reservation_quota=quota_cache,
                ).create(
                    ReservationPlanRequest(
                        pool_id=pool_id,
                        preferred_device_id=device_id,
                        start_date=current_day,
                        end_date=current_day,
                        purpose="占用不同日期上的不同实物设备",
                    ),
                    idempotency_key=f"{prefix}-split-{current_day.isoformat()}",
                )

        first_day_hash = await quota_cache.redis.hgetall(
            quota_cache._quota_key(pool_id, first_day)
        )
        second_day_hash = await quota_cache.redis.hgetall(
            quota_cache._quota_key(pool_id, second_day)
        )
        assert first_day_hash == {str(device_ids[0]): "0", str(device_ids[1]): "1"}
        assert second_day_hash == {str(device_ids[0]): "1", str(device_ids[1]): "0"}

        async with factory() as session:
            with pytest.raises(ApiError) as discontinuous:
                await ReservationService(
                    session,
                    principal,
                    reservation_quota=quota_cache,
                ).create(
                    continuous_plan,
                    idempotency_key=f"{prefix}-continuous-request",
                )
            assert discontinuous.value.status_code == 409
            assert discontinuous.value.code == "RESERVATION_DEVICE_NOT_CONTINUOUS"

        assert await quota_cache.redis.hgetall(
            quota_cache._quota_key(pool_id, first_day)
        ) == first_day_hash
        assert await quota_cache.redis.hgetall(
            quota_cache._quota_key(pool_id, second_day)
        ) == second_day_hash

        async with factory() as session:
            occupancy = int(
                await session.scalar(
                    select(func.count(ReservationItem.id)).where(
                        ReservationItem.device_id.in_(device_ids),
                        ReservationItem.reservation_date.in_((first_day, second_day)),
                    )
                )
                or 0
            )
            assert occupancy == 2
    finally:
        if quota_app is not None:
            await dispose_app_redis(quota_app)
        if engine is not None:
            await engine.dispose()
        await cleanup(prefix)


@pytest.mark.asyncio
async def test_mysql_resource_pool_concurrency_never_exceeds_physical_quantity(capsys) -> None:
    if os.getenv("LAB_RUN_MYSQL_INTEGRATION") != "1":
        pytest.skip("set LAB_RUN_MYSQL_INTEGRATION=1 to run against the configured MySQL")

    settings = Settings()
    if settings.mysql_dsn.startswith("sqlite"):
        pytest.skip("this test verifies MySQL pool-row locking and unique-index semantics")

    prefix = f"e2e-pool-race-{secrets.token_hex(4)}"
    engine = None
    quota_app = None
    try:
        await seed(prefix)
        capsys.readouterr()
        engine = build_engine(settings)
        factory = build_session_factory(engine)
        quota_app, quota_cache = _reservation_quota_for_settings(settings)
        assert await quota_cache.redis.ping() is True
        async with factory() as session:
            student = await session.scalar(select(User).where(User.username == f"{prefix}-user"))
            student_role = await session.scalar(
                select(Role).where(Role.role_code == "STUDENT")
            )
            device = await session.scalar(select(Device).where(Device.name == f"{prefix}-device"))
            assert student is not None and student_role is not None and device is not None
            if device.pool_id is None:
                pool = DevicePool(
                    name=device.name,
                    college_id=device.college_id,
                    lab_id=device.lab_id,
                )
                session.add(pool)
                await session.flush()
                device.pool_id = pool.id
            second_unit = Device(
                pool_id=device.pool_id,
                college_id=device.college_id,
                lab_id=device.lab_id,
                category_id=device.category_id,
                name=device.name,
                brand=device.brand,
                model=device.model,
                specs=device.specs,
                image_url=device.image_url,
                status="IDLE",
                need_approval=device.need_approval,
                max_reservation_days=device.max_reservation_days,
                tags=device.tags,
                accessory_checklist=device.accessory_checklist,
                allow_external_loan=device.allow_external_loan,
                risk_level=device.risk_level,
                requires_safety_ack=device.requires_safety_ack,
                requires_qualification=device.requires_qualification,
                max_advance_days=device.max_advance_days,
                asset_code=f"{prefix}-unit-2",
            )
            session.add(second_unit)
            await session.flush()
            pool_id = int(device.pool_id)
            physical_device_ids = [device.id, second_unit.id]
            contenders = [student]
            for index in range(1, 5):
                contender = User(
                    username=f"{prefix}-pool-user-{index}",
                    password_hash=student.password_hash,
                    real_name=f"资源池并发用户 {index}",
                    user_type="STUDENT",
                    college_id=student.college_id,
                    status=1,
                    roles=[student_role],
                )
                contenders.append(contender)
            session.add_all(contenders[1:])
            await session.flush()
            principals = [
                Principal(
                    user_id=user.id,
                    username=user.username,
                    college_id=user.college_id,
                    roles=("STUDENT",),
                    token_type="access",
                    token_id=f"mysql-pool-race-{index}-{secrets.token_hex(4)}",
                    permissions=("reservation:create",),
                )
                for index, user in enumerate(contenders)
            ]
            await session.commit()

        target_date = date.today() + timedelta(days=10)
        quota_key = quota_cache._quota_key(pool_id, target_date)
        plan = ReservationPlanRequest(
            pool_id=pool_id,
            start_date=target_date,
            end_date=target_date,
            purpose="资源池并发预约容量验证",
        )

        async with factory() as session:
            preflight = await ReservationService(
                session,
                principals[0],
                reservation_quota=quota_cache,
            ).preflight(plan)
            assert preflight.all_available is True
        assert await quota_cache.redis.hgetall(quota_key) == {
            str(device_id): "1" for device_id in physical_device_ids
        }

        async def submit(contender: int):
            async with factory() as session:
                return await ReservationService(
                    session,
                    principals[contender],
                    reservation_quota=quota_cache,
                ).create(
                    plan.model_copy(update={"purpose": f"资源池并发预约 {contender}"}),
                    idempotency_key=f"{prefix}-request-{contender}",
                )

        outcomes = await asyncio.gather(
            *(submit(contender) for contender in range(5)),
            return_exceptions=True,
        )
        successes = [outcome for outcome in outcomes if not isinstance(outcome, BaseException)]
        failures = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
        assert len(successes) == 2, outcomes
        assert len(failures) == 3, outcomes
        assert all(
            isinstance(error, ApiError)
            and error.status_code == 409
            and error.code in {"RESERVATION_CONFLICT", "RESERVATION_QUOTA_INSUFFICIENT"}
            for error in failures
        ), failures
        assert await quota_cache.redis.hgetall(quota_key) == {
            str(device_id): "0" for device_id in physical_device_ids
        }
        allocated_device_ids = {result.created[0].device_id for result in successes}
        assert len(allocated_device_ids) == 2

        async with factory() as session:
            occupied_rows = int(
                await session.scalar(
                    select(func.count(ReservationItem.id)).where(
                        ReservationItem.device_id.in_(allocated_device_ids),
                        ReservationItem.reservation_date == target_date,
                    )
                )
                or 0
            )
            assert occupied_rows == 2
    finally:
        if quota_app is not None:
            await dispose_app_redis(quota_app)
        if engine is not None:
            await engine.dispose()
        await cleanup(prefix)


@pytest.mark.asyncio
async def test_mysql_pool_allows_overlapping_ranges_up_to_concurrent_user_count(capsys) -> None:
    if os.getenv("LAB_RUN_MYSQL_INTEGRATION") != "1":
        pytest.skip("set LAB_RUN_MYSQL_INTEGRATION=1 to run against the configured MySQL")

    settings = Settings()
    if settings.mysql_dsn.startswith("sqlite"):
        pytest.skip("this test verifies MySQL row-lock and unique-index semantics")

    prefix = f"e2e-pool-overlap-{secrets.token_hex(4)}"
    engine = None
    try:
        await seed(prefix, pool_units=3)
        capsys.readouterr()
        engine = build_engine(settings)
        factory = build_session_factory(engine)
        async with factory() as session:
            student = await session.scalar(select(User).where(User.username == f"{prefix}-user"))
            alternate = await session.scalar(
                select(User).where(User.username == f"{prefix}-user2")
            )
            device = await session.scalar(select(Device).where(Device.name == f"{prefix}-device"))
            student_role = await session.scalar(
                select(Role).where(Role.role_code == "STUDENT")
            )
            assert student is not None and alternate is not None
            assert device is not None and device.pool_id is not None and student_role is not None

            third_user = User(
                username=f"{prefix}-user3",
                password_hash=student.password_hash,
                real_name="第三位并发预约用户",
                user_type="STUDENT",
                college_id=student.college_id,
                status=1,
                roles=[student_role],
            )
            fourth_user = User(
                username=f"{prefix}-user4",
                password_hash=student.password_hash,
                real_name="第四位并发预约用户",
                user_type="STUDENT",
                college_id=student.college_id,
                status=1,
                roles=[student_role],
            )
            session.add_all([third_user, fourth_user])
            await session.flush()
            users = [student, alternate, third_user, fourth_user]
            principals = [
                Principal(
                    user_id=user.id,
                    username=user.username,
                    college_id=user.college_id,
                    roles=("STUDENT",),
                    token_type="access",
                    token_id=f"mysql-pool-overlap-{index}-{secrets.token_hex(4)}",
                    permissions=("reservation:create",),
                )
                for index, user in enumerate(users)
            ]
            pool_id = device.pool_id
            pool_device_ids = set(
                (
                    await session.scalars(
                        select(Device.id).where(Device.pool_id == pool_id)
                    )
                ).all()
            )
            await session.commit()

        first_day = date.today() + timedelta(days=10)
        plans = [
            ReservationPlanRequest(
                pool_id=pool_id,
                start_date=first_day,
                end_date=first_day + timedelta(days=1),
                purpose="容量充足时的重叠预约 A",
            ),
            ReservationPlanRequest(
                pool_id=pool_id,
                start_date=first_day + timedelta(days=1),
                end_date=first_day + timedelta(days=2),
                purpose="容量充足时的重叠预约 B",
            ),
            ReservationPlanRequest(
                pool_id=pool_id,
                start_date=first_day + timedelta(days=1),
                end_date=first_day + timedelta(days=1),
                purpose="容量充足时的重叠预约 C",
            ),
        ]
        ready = 0
        ready_lock = asyncio.Lock()
        start_together = asyncio.Event()

        async def submit(index: int):
            nonlocal ready
            async with factory() as session:
                async with ready_lock:
                    ready += 1
                    if ready == len(plans):
                        start_together.set()
                await start_together.wait()
                return await ReservationService(session, principals[index]).create(
                    plans[index],
                    idempotency_key=f"{prefix}-overlap-{index}",
                )

        outcomes = await asyncio.gather(
            *(submit(index) for index in range(len(plans))),
            return_exceptions=True,
        )
        successes = [outcome for outcome in outcomes if not isinstance(outcome, BaseException)]
        failures = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
        assert len(successes) == 3, outcomes
        assert failures == [], outcomes
        allocated_device_ids = {outcome.created[0].device_id for outcome in successes}
        assert len(allocated_device_ids) == 3

        async with factory() as session:
            occupancy_rows = (
                await session.execute(
                    select(ReservationItem.reservation_date, func.count(ReservationItem.id))
                    .where(
                        ReservationItem.device_id.in_(pool_device_ids),
                        ReservationItem.reservation_date.between(
                            first_day,
                            first_day + timedelta(days=2),
                        ),
                    )
                    .group_by(ReservationItem.reservation_date)
                )
            ).all()
            occupancy = {row[0]: int(row[1]) for row in occupancy_rows}
            assert occupancy == {
                first_day: 1,
                first_day + timedelta(days=1): 3,
                first_day + timedelta(days=2): 1,
            }

        async with factory() as session:
            with pytest.raises(ApiError) as exhausted:
                await ReservationService(session, principals[3]).create(
                    ReservationPlanRequest(
                        pool_id=pool_id,
                        start_date=first_day + timedelta(days=1),
                        end_date=first_day + timedelta(days=1),
                        purpose="同一天超出三台库存的第四笔预约",
                    ),
                    idempotency_key=f"{prefix}-overlap-extra",
                )
            assert exhausted.value.status_code == 409
    finally:
        if engine is not None:
            await engine.dispose()
        await cleanup(prefix)


@pytest.mark.asyncio
async def test_mysql_concurrent_partially_overlapping_ranges_has_one_winner(capsys) -> None:
    if os.getenv("LAB_RUN_MYSQL_INTEGRATION") != "1":
        pytest.skip("set LAB_RUN_MYSQL_INTEGRATION=1 to run against the configured MySQL")

    settings = Settings()
    if settings.mysql_dsn.startswith("sqlite"):
        pytest.skip("this test verifies MySQL transaction and unique-index semantics")

    prefix = f"e2e-reservation-overlap-race-{secrets.token_hex(4)}"
    engine = None
    try:
        await seed(prefix)
        capsys.readouterr()
        engine = build_engine(settings)
        factory = build_session_factory(engine)
        async with factory() as session:
            student = await session.scalar(select(User).where(User.username == f"{prefix}-user"))
            device = await session.scalar(select(Device).where(Device.name == f"{prefix}-device"))
            student_role = await session.scalar(
                select(Role).where(Role.role_code == "STUDENT")
            )
            assert student is not None and device is not None and student_role is not None
            alternate = User(
                username=f"{prefix}-overlap-user-2",
                password_hash=student.password_hash,
                real_name="重叠区间并发用户二",
                user_type="STUDENT",
                college_id=student.college_id,
                status=1,
                roles=[student_role],
            )
            session.add(alternate)
            await session.flush()
            principals = [
                Principal(
                    user_id=user.id,
                    username=user.username,
                    college_id=user.college_id,
                    roles=("STUDENT",),
                    token_type="access",
                    token_id=f"mysql-reservation-overlap-{index}-{secrets.token_hex(4)}",
                    permissions=("reservation:create",),
                )
                for index, user in enumerate((student, alternate))
            ]
            device_id = device.id
            await session.commit()

        overlap_start = date.today() + timedelta(days=10)
        plans = [
            ReservationPlanRequest(
                device_id=device_id,
                start_date=overlap_start,
                end_date=overlap_start + timedelta(days=2),
                purpose="并发预约区间 A",
            ),
            ReservationPlanRequest(
                device_id=device_id,
                start_date=overlap_start + timedelta(days=1),
                end_date=overlap_start + timedelta(days=3),
                purpose="并发预约区间 B",
            ),
        ]
        ready = 0
        ready_lock = asyncio.Lock()
        start_together = asyncio.Event()

        async def submit(index: int):
            nonlocal ready
            async with factory() as session:
                service = ReservationService(session, principals[index])
                async with ready_lock:
                    ready += 1
                    if ready == len(plans):
                        start_together.set()
                await start_together.wait()
                result = await service.create(
                    plans[index],
                    idempotency_key=f"{prefix}-request-{index}",
                )
                return index, result

        outcomes = await asyncio.gather(
            *(submit(index) for index in range(len(plans))),
            return_exceptions=True,
        )
        successes = [outcome for outcome in outcomes if not isinstance(outcome, BaseException)]
        failures = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]

        assert len(successes) == 1, outcomes
        assert len(failures) == 1, outcomes
        assert isinstance(failures[0], ApiError) and failures[0].status_code == 409, outcomes
        winning_start = overlap_start if successes[0][0] == 0 else overlap_start + timedelta(days=1)

        async with factory() as session:
            persisted_reservations = list(
                (
                    await session.scalars(
                        select(Reservation).where(
                            Reservation.device_id == device_id,
                            Reservation.start_date <= overlap_start + timedelta(days=3),
                            Reservation.end_date >= overlap_start,
                        )
                    )
                ).all()
            )
            occupied_days = list(
                (
                    await session.scalars(
                        select(ReservationItem).where(
                            ReservationItem.device_id == device_id,
                            ReservationItem.reservation_date.between(
                                overlap_start,
                                overlap_start + timedelta(days=3),
                            ),
                        )
                    )
                ).all()
            )

        assert len(persisted_reservations) == 1
        assert len(occupied_days) == 3
        assert {item.reservation_date for item in occupied_days} == {
            winning_start + timedelta(days=offset) for offset in range(3)
        }
        assert {item.reservation_id for item in occupied_days} == {persisted_reservations[0].id}
    finally:
        if engine is not None:
            await engine.dispose()
        await cleanup(prefix)


@pytest.mark.asyncio
async def test_mysql_1000_concurrent_api_requests_are_bounded_and_never_overbook(capsys) -> None:
    if os.getenv("LAB_RUN_MYSQL_INTEGRATION") != "1":
        pytest.skip("set LAB_RUN_MYSQL_INTEGRATION=1 to run against the configured MySQL")
    if os.getenv("LAB_RUN_1000_CONCURRENCY") != "1":
        pytest.skip("set LAB_RUN_1000_CONCURRENCY=1 to run the isolated 1,000-request API test")

    settings = Settings()
    if settings.mysql_dsn.startswith("sqlite"):
        pytest.skip("this test verifies MySQL and Redis behavior through the API stack")

    prefix = f"e2e-reservation-load-{secrets.token_hex(4)}"
    engine = None
    app = None
    try:
        await seed(prefix)
        fixture = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        engine = build_engine(settings)
        factory = build_session_factory(engine)
        async with factory() as session:
            device = await session.scalar(select(Device).where(Device.name == f"{prefix}-device"))
            assert device is not None
            device_id = device.id

        app_settings = settings.model_copy(
            update={
                "environment": "test",
                "enable_workers": False,
                "rate_limit_enabled": False,
                # Keep this 1,000-request test deliberately above the finite
                # admission budget so it also exercises the 503 backpressure
                # path instead of allowing the default 1,000-entry queue to
                # absorb the entire burst.
                "request_queue_capacity": 100,
                "cors_origins": ["http://test"],
            }
        )
        app = create_app(app_settings)
        target_date = date.today() + timedelta(days=10)
        payload = {
            "device_id": device_id,
            "start_date": target_date.isoformat(),
            "end_date": target_date.isoformat(),
            "purpose": "隔离环境并发容量验证",
        }

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            timeout=30,
        ) as client:
            csrf_response = await client.get("/api/v2/auth/csrf")
            assert csrf_response.status_code == 200, csrf_response.text
            csrf_token = csrf_response.json()["data"]["csrf_token"]
            login_response = await client.post(
                "/api/v2/auth/login",
                json={"username": fixture["username"], "password": fixture["password"]},
                headers={"Origin": "http://test", "X-CSRF-Token": csrf_token},
            )
            assert login_response.status_code == 200, login_response.text
            csrf_token = login_response.json()["data"]["csrf_token"]
            request_headers = {
                "Origin": "http://test",
                "X-CSRF-Token": csrf_token,
            }
            responses = await asyncio.gather(
                *(
                    client.post(
                        "/api/v2/reservations",
                        json=payload,
                        headers={
                            **request_headers,
                            "Idempotency-Key": f"{prefix}-request-{contender}",
                        },
                    )
                    for contender in range(1000)
                )
            )

        status_counts = Counter(response.status_code for response in responses)
        print(f"isolated 1,000-request HTTP status counts: {dict(status_counts)}")
        assert status_counts[201] == 1, (
            f"expected one winner; HTTP status counts={dict(status_counts)}"
        )
        assert status_counts[409] >= 1, (
            f"expected conflict responses; HTTP status counts={dict(status_counts)}"
        )
        assert status_counts[503] >= 1, (
            f"expected bounded overload responses; HTTP status counts={dict(status_counts)}"
        )
        assert sum(status_counts.values()) == 1000
        assert set(status_counts).issubset({201, 409, 503}), status_counts

        async with factory() as session:
            occupied_rows = int(
                await session.scalar(
                    select(func.count(ReservationItem.id)).where(
                        ReservationItem.device_id == device_id,
                        ReservationItem.reservation_date == target_date,
                    )
                )
                or 0
            )
            assert occupied_rows == 1
    finally:
        if app is not None:
            await dispose_app_redis(app)
        if engine is not None:
            await engine.dispose()
        await cleanup(prefix)


@pytest.mark.asyncio
async def test_mysql_concurrent_device_rule_sync_is_an_atomic_upsert() -> None:
    if os.getenv("LAB_RUN_MYSQL_INTEGRATION") != "1":
        pytest.skip("set LAB_RUN_MYSQL_INTEGRATION=1 to run against the configured MySQL")

    settings = Settings()
    if settings.mysql_dsn.startswith("sqlite"):
        pytest.skip("this test verifies MySQL upsert and unique-index semantics")

    prefix = f"e2e-device-rule-race-{secrets.token_hex(4)}"
    engine = None
    try:
        await seed(prefix)
        engine = build_engine(settings)
        factory = build_session_factory(engine)
        async with factory() as session:
            student = await session.scalar(select(User).where(User.username == f"{prefix}-user"))
            device = await session.scalar(select(Device).where(Device.name == f"{prefix}-device"))
            assert student is not None and device is not None
            device_id = device.id
            user_id = student.id

        async def synchronize():
            async with factory() as session:
                device = await session.scalar(select(Device).where(Device.id == device_id))
                assert device is not None
                await _sync_device_reservation_rule(session, device, user_id)
                await session.commit()

        outcomes = await asyncio.gather(
            *(synchronize() for _ in range(12)),
            return_exceptions=True,
        )
        assert outcomes == [None] * len(outcomes), outcomes

        async with factory() as session:
            rules = list(
                (
                    await session.scalars(
                        select(ReservationRule).where(
                            ReservationRule.scope_type == "DEVICE",
                            ReservationRule.scope_id == device_id,
                            ReservationRule.user_category == "ALL",
                        )
                    )
                ).all()
            )
            assert len(rules) == 1
            assert rules[0].max_booking_days == 8
            assert rules[0].approval_required is True
    finally:
        if engine is not None:
            await engine.dispose()
        await cleanup(prefix)


@pytest.mark.asyncio
async def test_mysql_maintenance_evidence_submission_races_safely_with_cleanup() -> None:
    if os.getenv("LAB_RUN_MYSQL_INTEGRATION") != "1":
        pytest.skip("set LAB_RUN_MYSQL_INTEGRATION=1 to run against the configured MySQL")

    settings = Settings()
    if settings.mysql_dsn.startswith("sqlite"):
        pytest.skip("this test verifies MySQL locking reads and foreign-key semantics")

    prefix = f"e2e-maintenance-upload-race-{secrets.token_hex(4)}"
    engine = None
    try:
        await seed(prefix)
        engine = build_engine(settings)
        factory = build_session_factory(engine)
        async with factory() as session:
            manager = await session.scalar(select(User).where(User.username == f"{prefix}-manager"))
            device = await session.scalar(select(Device).where(Device.name == f"{prefix}-device"))
            assert manager is not None and device is not None
            manager_principal = Principal(
                user_id=manager.id,
                username=manager.username,
                college_id=manager.college_id,
                roles=("LAB_ADMIN",),
                token_type="access",
                token_id=f"maintenance-upload-race-{secrets.token_hex(6)}",
                permissions=("maintenance:manage",),
            )
            manager_id = manager.id
            college_id = manager.college_id
            device_id = device.id

        with TemporaryDirectory(prefix="lab-maintenance-evidence-") as upload_dir:
            evidence_path = Path(upload_dir) / "calibration-proof.pdf"
            evidence_path.write_bytes(b"%PDF-1.7 concurrency regression")
            token = f"maintenance-race-proof-{secrets.token_hex(8)}"
            async with factory() as session:
                plan = await MaintenanceService(session, manager_principal).create_plan(
                    device_id,
                    MaintenancePlanWrite(
                        plan_type="CALIBRATION",
                        title="并发清理校准计划",
                        interval_value=1,
                        interval_unit="YEAR",
                        due_date=date.today(),
                    ),
                )
                session.add(
                    UploadAsset(
                        asset_token=token,
                        user_id=manager_id,
                        college_id=college_id,
                        original_name="calibration-proof.pdf",
                        content_type="application/pdf",
                        size_bytes=evidence_path.stat().st_size,
                        storage_path=str(evidence_path),
                        created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=2),
                    )
                )
                await session.commit()
                plan_id = plan.id

            async def submit_record():
                async with factory() as session:
                    return await MaintenanceService(session, manager_principal).complete_cycle(
                        plan_id,
                        MaintenanceRecordCreate(
                            cycle_due_date=date.today(),
                            completed_date=date.today(),
                            result="PASSED",
                            evidence_asset_token=token,
                        ),
                        idempotency_key=f"maintenance-upload-race-{secrets.token_hex(8)}",
                    )

            async def cleanup_upload():
                async with factory() as session:
                    return await cleanup_orphan_uploads(session, upload_dir)

            submission, cleanup_result = await asyncio.gather(
                submit_record(), cleanup_upload(), return_exceptions=True
            )
            assert not isinstance(cleanup_result, BaseException), cleanup_result
            submission_detail = (
                f"submission={submission}; "
                f"statement={getattr(submission, 'statement', None)!r}; "
                f"orig={getattr(submission, 'orig', None)!r}"
            )
            assert not isinstance(submission, BaseException) or (
                isinstance(submission, ApiError) and submission.code == "EVIDENCE_NOT_FOUND"
            ), submission_detail

            async with factory() as session:
                record_count = int(
                    await session.scalar(
                        select(func.count(DeviceMaintenanceRecord.id)).where(
                            DeviceMaintenanceRecord.plan_id == plan_id
                        )
                    )
                    or 0
                )
                if isinstance(submission, BaseException):
                    assert record_count == 0
                else:
                    assert record_count == 1
                    assert evidence_path.exists()
    finally:
        if engine is not None:
            await engine.dispose()
        await cleanup(prefix)


@pytest.mark.asyncio
async def test_mysql_concurrent_outbox_claim_delivers_maintenance_due_once() -> None:
    if os.getenv("LAB_RUN_MYSQL_INTEGRATION") != "1":
        pytest.skip("set LAB_RUN_MYSQL_INTEGRATION=1 to run against the configured MySQL")

    settings = Settings()
    if settings.mysql_dsn.startswith("sqlite"):
        pytest.skip("this test verifies MySQL SKIP LOCKED and row-lock semantics")

    prefix = f"e2e-maintenance-due-race-{secrets.token_hex(4)}"
    engine = None
    try:
        await seed(prefix)
        engine = build_engine(settings)
        factory = build_session_factory(engine)
        async with factory() as session:
            manager = await session.scalar(select(User).where(User.username == f"{prefix}-manager"))
            device = await session.scalar(select(Device).where(Device.name == f"{prefix}-device"))
            assert manager is not None and device is not None
            device_id = device.id
            college_id = device.college_id
            manager_id = manager.id

        due_date = date.today()
        task_key = f"mysql-maintenance-due-race-{secrets.token_hex(8)}"
        async with factory() as session:
            plan = DeviceMaintenancePlan(
                device_id=device_id,
                college_id=college_id,
                plan_type="ROUTINE",
                title="并发到期提醒验证",
                interval_value=1,
                interval_unit="YEAR",
                due_date=due_date,
                active=True,
                created_by=manager_id,
                updated_by=manager_id,
            )
            session.add(plan)
            await session.flush()
            plan_id = plan.id
            session.add(
                OutboxTask(
                    task_key=task_key,
                    task_type="MAINTENANCE_DUE",
                    aggregate_key=f"maintenance:{plan_id}",
                    college_id=college_id,
                    payload={"plan_id": plan_id, "due_date": due_date.isoformat()},
                    status="PENDING",
                    execute_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1),
                )
            )
            await session.commit()

            app = FastAPI()
            app.state.session_factory = factory
            app.state.settings = settings

            class IsolatedOutboxWorker(OutboxWorker):
                async def _claim_one(self):
                    return await super()._claim_one(only_task_key=task_key)

            worker = IsolatedOutboxWorker(app)
        outcomes = await asyncio.gather(
            *(worker.run_once() for _ in range(8)),
            return_exceptions=True,
        )
        assert all(isinstance(outcome, bool) for outcome in outcomes), outcomes
        assert sum(outcomes) == 1, outcomes

        async with factory() as session:
            plan = await session.get(DeviceMaintenancePlan, plan_id)
            event_task = await session.scalar(
                select(OutboxTask).where(OutboxTask.task_key == task_key)
            )
            notice_count = int(
                await session.scalar(
                    select(func.count(OutboxTask.id)).where(
                        OutboxTask.task_type == "NOTIFICATION",
                        OutboxTask.aggregate_key
                        == f"maintenance:{plan_id}:due:{due_date.isoformat()}",
                    )
                )
                or 0
            )
            assert plan is not None and plan.due_notice_sent_at is not None
            assert event_task is not None and event_task.status == "COMPLETED"
            assert notice_count == 1
    finally:
        if engine is not None:
            await engine.dispose()
        await cleanup(prefix)
