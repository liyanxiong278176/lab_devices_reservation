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
from app.infrastructure.cache.redis import dispose_app_redis
from app.infrastructure.db.models import (
    Device,
    DeviceMaintenancePlan,
    DeviceMaintenanceRecord,
    OutboxTask,
    Reservation,
    ReservationItem,
    ReservationRule,
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
            device = await session.scalar(select(Device).where(Device.name == f"{prefix}-device"))
            assert student is not None and device is not None
            principal = Principal(
                user_id=student.id,
                username=student.username,
                college_id=student.college_id,
                roles=("STUDENT",),
                token_type="access",
                token_id=f"mysql-reservation-race-{secrets.token_hex(6)}",
                permissions=("reservation:create",),
            )
            device_id = device.id

        target_date = date.today() + timedelta(days=10)

        async def submit(contender: int):
            async with factory() as session:
                service = ReservationService(session, principal)
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
            assert student is not None and device is not None
            principal = Principal(
                user_id=student.id,
                username=student.username,
                college_id=student.college_id,
                roles=("STUDENT",),
                token_type="access",
                token_id=f"mysql-reservation-overlap-{secrets.token_hex(6)}",
                permissions=("reservation:create",),
            )
            device_id = device.id

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
                service = ReservationService(session, principal)
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
        winning_start = (
            overlap_start
            if successes[0][0] == 0
            else overlap_start + timedelta(days=1)
        )

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
        assert {item.reservation_id for item in occupied_days} == {
            persisted_reservations[0].id
        }
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
