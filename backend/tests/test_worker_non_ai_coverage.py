from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from app.api.v2.schemas import ReservationPlanRequest
from app.application.repairs import RepairService
from app.application.reservations import ReservationService
from app.auth.security import Principal
from app.core.settings import Settings
from app.infrastructure.db.models import (
    Device,
    DeviceMaintenancePlan,
    ExportTask,
    OutboxTask,
    RepairReport,
    RepairWorklog,
    Reservation,
    ReservationBlackout,
    ReservationWaitlist,
    ReservationWaitlistOffer,
    Role,
    User,
)
from app.infrastructure.tasks import worker as worker_module
from app.infrastructure.tasks.worker import OutboxWorker
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


def _app(factory, *, upload_dir: Path | None = None, **settings_overrides) -> FastAPI:
    app = FastAPI()
    app.state.settings = Settings(
        environment="test",
        cors_origins=[],
        enable_workers=False,
        upload_dir=str(upload_dir) if upload_dir else "uploads",
        **settings_overrides,
    )
    app.state.session_factory = factory
    return app


def _principal(user: User, *roles: str) -> Principal:
    permissions = {
        "STUDENT": ("repair:create", "repair:read:own", "repair:confirm"),
        "LAB_ADMIN": ("repair:read:scope", "repair:handle"),
    }
    return Principal(
        user_id=user.id,
        username=user.username,
        college_id=user.college_id,
        roles=roles,
        token_type="access",
        token_id="worker-non-ai-coverage",
        permissions=tuple(code for role in roles for code in permissions.get(role, ())),
    )


@pytest.mark.asyncio
async def test_worker_run_once_empty_failure_retry_and_metrics(seeded, monkeypatch) -> None:
    factory, _, _, student, *_ = seeded
    app = _app(factory, outbox_retry_base_seconds=1)
    metrics = SimpleNamespace(increment=Mock(), set_gauge=Mock())
    app.state.metrics = metrics
    worker = OutboxWorker(app, poll_seconds=0.001)

    assert await worker.run_once() is False
    await worker._mark_completed(999999)
    await worker._mark_failed(999999, "missing task", RuntimeError("not found"))

    async with factory() as session:
        retry = OutboxTask(
            task_key="coverage:retry",
            task_type="CACHE_BUMP",
            aggregate_key=None,
            payload={"scope": f"college:{student.college_id}"},
            status="PROCESSING",
            attempts=1,
            execute_at=datetime.now(UTC).replace(tzinfo=None),
        )
        permanent = OutboxTask(
            task_key="coverage:permanent",
            task_type="CACHE_BUMP",
            aggregate_key=None,
            payload={},
            status="PROCESSING",
            attempts=1,
            execute_at=datetime.now(UTC).replace(tzinfo=None),
        )
        session.add_all([retry, permanent])
        await session.commit()
        retry_id, permanent_id = retry.id, permanent.id

    await worker._mark_failed(retry_id, "temporary", RuntimeError("temporary"))
    await worker._mark_failed(permanent_id, "x" * 2100, ValueError("invalid payload"))
    async with factory() as session:
        retry = await session.get(OutboxTask, retry_id)
        permanent = await session.get(OutboxTask, permanent_id)
        assert retry is not None and retry.status == "PENDING"
        assert retry.execute_at > datetime.now(UTC).replace(tzinfo=None)
        assert permanent is not None and permanent.status == "FAILED"
        assert len(permanent.last_error or "") == 2000

    metrics.increment.assert_any_call(
        "outbox_failed_total",
        labels={"status": "PENDING", "task_type": "CACHE_BUMP"},
    )
    worker._metric("test_metric", {"status": "ok"})
    worker._set_active_tasks(3)
    metrics.increment.assert_any_call("test_metric", labels={"status": "ok"})
    metrics.set_gauge.assert_called_once_with("outbox_worker_active_tasks", 3)


@pytest.mark.asyncio
async def test_worker_process_claimed_success_failure_and_cancellation(seeded, monkeypatch) -> None:
    factory, *_ = seeded
    worker = OutboxWorker(_app(factory), poll_seconds=0.001)
    worker._handle = AsyncMock()
    worker._mark_completed = AsyncMock()
    await worker._process_claimed((1, "success", "CACHE_BUMP", {}, None))
    worker._mark_completed.assert_awaited_once_with(1)

    worker._handle = AsyncMock(side_effect=RuntimeError("dependency unavailable"))
    worker._mark_failed = AsyncMock()
    await worker._process_claimed((2, "failure", "CACHE_BUMP", {}, None))
    worker._mark_failed.assert_awaited_once()
    assert worker._mark_failed.await_args.args == (
        2,
        "dependency unavailable",
        worker._handle.side_effect,
    )

    worker._handle = AsyncMock(side_effect=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await worker._process_claimed((3, "cancelled", "CACHE_BUMP", {}, None))
    worker._mark_failed.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_claim_filters_aggregate_order_and_null_leases(seeded) -> None:
    factory, *_ = seeded
    app = _app(factory, outbox_claim_timeout_seconds=1, outbox_max_attempts=2)
    worker = OutboxWorker(app)
    now = datetime.now(UTC).replace(tzinfo=None)
    async with factory() as session:
        session.add_all(
            [
                OutboxTask(
                    task_key="coverage:aggregate:processing",
                    task_type="NOTIFICATION",
                    aggregate_key="reservation:5",
                    payload={},
                    status="PROCESSING",
                    attempts=1,
                    claimed_at=now,
                    execute_at=now,
                ),
                OutboxTask(
                    task_key="coverage:aggregate:pending",
                    task_type="NOTIFICATION",
                    aggregate_key="reservation:5",
                    payload={},
                    status="PENDING",
                    attempts=0,
                    execute_at=now,
                ),
                OutboxTask(
                    task_key="coverage:no-aggregate",
                    task_type="CACHE_BUMP",
                    aggregate_key=None,
                    payload={"scope": "college:1"},
                    execute_at=now,
                ),
                OutboxTask(
                    task_key="coverage:aggregate:unblocked",
                    task_type="NOTIFICATION",
                    aggregate_key="reservation:unblocked",
                    payload={},
                    execute_at=now,
                ),
                OutboxTask(
                    task_key="coverage:exhausted-null-lease",
                    task_type="CACHE_BUMP",
                    aggregate_key=None,
                    payload={},
                    status="PROCESSING",
                    attempts=2,
                    claimed_at=None,
                    execute_at=now,
                ),
            ]
        )
        await session.commit()

    assert await worker._claim_one(only_task_key="coverage:aggregate:pending") is None
    claim = await worker._claim_one(only_task_key="coverage:aggregate:unblocked")
    assert claim is not None and claim[1] == "coverage:aggregate:unblocked"
    claim = await worker._claim_one(only_task_key="coverage:no-aggregate")
    assert claim is not None and claim[1] == "coverage:no-aggregate"
    assert await worker._claim_one(only_task_key="coverage:exhausted-null-lease") is None
    async with factory() as session:
        exhausted = await session.scalar(
            select(OutboxTask).where(OutboxTask.task_key == "coverage:exhausted-null-lease")
        )
        assert exhausted is not None and exhausted.status == "FAILED"


@pytest.mark.asyncio
async def test_worker_run_drains_active_task_and_start_stop_lifecycle(seeded, monkeypatch) -> None:
    factory, *_ = seeded
    worker = OutboxWorker(_app(factory), poll_seconds=0.001)
    claimed = (1, "run-task", "CACHE_BUMP", {}, None)
    calls = 0
    finished = asyncio.Event()

    async def claim_one():
        nonlocal calls
        calls += 1
        return claimed if calls == 1 else None

    async def process(_claimed):
        finished.set()
        worker._stop.set()

    monkeypatch.setattr(worker, "_claim_one", claim_one)
    monkeypatch.setattr(worker, "_process_claimed", process)
    await worker._run()
    assert finished.is_set()
    assert calls == 2

    async def wait_until_stopped():
        await worker._stop.wait()

    monkeypatch.setattr(worker, "_run", wait_until_stopped)
    await worker.start()
    await worker.stop()
    assert worker._task is None
    await worker.stop()


@pytest.mark.asyncio
async def test_worker_loop_handles_cancel_poll_stop_wrapper_failure_and_drain(
    seeded,
    monkeypatch,
) -> None:
    factory, *_ = seeded

    cancelled = OutboxWorker(_app(factory), poll_seconds=0.001)
    monkeypatch.setattr(
        cancelled,
        "_claim_one",
        AsyncMock(side_effect=asyncio.CancelledError()),
    )
    with pytest.raises(asyncio.CancelledError):
        await cancelled._run()

    poll_failure = OutboxWorker(_app(factory), poll_seconds=0.001)
    monkeypatch.setattr(
        poll_failure,
        "_claim_one",
        AsyncMock(side_effect=RuntimeError("poll failure")),
    )

    async def stop_during_backoff(_timeout: float) -> None:
        poll_failure._stop.set()

    monkeypatch.setattr(poll_failure, "_wait_for_stop", stop_during_backoff)
    await poll_failure._run()

    wrapper_failure = OutboxWorker(_app(factory), poll_seconds=0.001)
    claimed = (11, "wrapper-error", "CACHE_BUMP", {}, None)
    poll_results = iter([claimed, None])
    monkeypatch.setattr(wrapper_failure, "_claim_one", lambda: _next_async(poll_results))

    async def fail_processing(_claimed) -> None:
        raise RuntimeError("processing wrapper failed")

    monkeypatch.setattr(wrapper_failure, "_process_claimed", fail_processing)

    async def stop_after_wrapper(_timeout: float) -> None:
        wrapper_failure._stop.set()

    monkeypatch.setattr(wrapper_failure, "_wait_for_stop", stop_after_wrapper)
    await wrapper_failure._run()

    outer_failure = OutboxWorker(_app(factory), poll_seconds=0.001)
    outer_claim = (12, "outer-error", "CACHE_BUMP", {}, None)

    async def claim_then_stop() -> tuple[int, str, str, dict[str, object], None]:
        outer_failure._stop.set()
        return outer_claim

    monkeypatch.setattr(outer_failure, "_claim_one", claim_then_stop)
    monkeypatch.setattr(outer_failure, "_process_claimed", AsyncMock())
    active_set_calls = 0

    def raise_once_then_clear(_count: int) -> None:
        nonlocal active_set_calls
        active_set_calls += 1
        if active_set_calls == 1:
            raise RuntimeError("metrics wrapper failed")

    monkeypatch.setattr(outer_failure, "_set_active_tasks", raise_once_then_clear)
    await outer_failure._run()
    assert active_set_calls == 2


@pytest.mark.asyncio
async def test_worker_loop_skips_poll_after_stop_and_propagates_cancelled_child(
    seeded,
    monkeypatch,
) -> None:
    factory, *_ = seeded
    stopped = OutboxWorker(_app(factory), poll_seconds=0.001)
    # The worker enters its outer loop, then observes shutdown before claiming
    # another task. This exercises the inner-loop stop branch directly.
    stopped._stop = SimpleNamespace(is_set=Mock(side_effect=[False, True, True]))
    monkeypatch.setattr(stopped, "_wait_for_stop", AsyncMock())
    await stopped._run()

    cancelled_child = OutboxWorker(
        _app(factory, outbox_worker_concurrency=1),
        poll_seconds=0.001,
    )
    monkeypatch.setattr(
        cancelled_child,
        "_claim_one",
        AsyncMock(return_value=(13, "cancelled-child", "CACHE_BUMP", {}, None)),
    )

    async def cancel_processing(_claimed) -> None:
        raise asyncio.CancelledError()

    monkeypatch.setattr(cancelled_child, "_process_claimed", cancel_processing)
    with pytest.raises(asyncio.CancelledError):
        await cancelled_child._run()


async def _next_async(iterator):
    return next(iterator)


@pytest.mark.asyncio
async def test_worker_notification_hub_relay_and_maintenance_without_manager(
    seeded,
    tmp_path,
    monkeypatch,
) -> None:
    factory, college, other_college, student, other_student, _, _, other_device = seeded
    app = _app(factory, upload_dir=tmp_path)
    hub = SimpleNamespace(publish=AsyncMock())
    app.state.notification_hub = hub
    worker = OutboxWorker(app)
    await worker._handle(
        "NOTIFICATION",
        {
            "user_id": student.id,
            "college_id": college.id,
            "title": "hub delivery",
            "content": "sent through the fallback hub",
        },
    )
    hub.publish.assert_awaited_once()

    relay = SimpleNamespace(publish=AsyncMock())
    app.state.notification_relay = relay
    await worker._handle(
        "NOTIFICATION",
        {
            "user_id": other_student.id,
            "college_id": other_college.id,
            "title": "relay delivery",
            "content": "sent through the relay",
        },
        task_key="coverage:notification:relay",
    )
    relay.publish.assert_awaited_once()

    async with factory() as session:
        plan = DeviceMaintenancePlan(
            device_id=other_device.id,
            college_id=other_college.id,
            plan_type="ROUTINE",
            title="Unmanaged device inspection",
            interval_value=1,
            interval_unit="MONTH",
            due_date=datetime.now(UTC).date() - timedelta(days=1),
            active=True,
            created_by=other_student.id,
            updated_by=other_student.id,
        )
        session.add(plan)
        await session.commit()
        plan_id = plan.id
        due_date = plan.due_date.isoformat()

    await worker._handle(
        "MAINTENANCE_DUE",
        {"plan_id": plan_id, "due_date": due_date},
        task_key="coverage:maintenance:no-manager",
    )
    async with factory() as session:
        plan = await session.get(DeviceMaintenancePlan, plan_id)
        assert plan is not None and plan.due_notice_sent_at is not None
        notices = list(
            (
                await session.scalars(
                    select(OutboxTask).where(
                        OutboxTask.aggregate_key == f"maintenance:{plan_id}:due:{due_date}"
                    )
                )
            ).all()
        )
        assert notices == []


@pytest.mark.asyncio
async def test_worker_repair_sla_invalid_missing_and_admin_fallback(seeded) -> None:
    factory, _college, other_college, _student, other_student, _, _, other_device = seeded
    worker = OutboxWorker(_app(factory))
    with pytest.raises(ValueError, match="unsupported repair SLA reminder kind"):
        await worker._handle("REPAIR_SLA_REMINDER", {"report_id": 999, "kind": "invalid"})
    await worker._handle(
        "REPAIR_SLA_REMINDER",
        {"report_id": 999999, "kind": "response"},
    )

    async with factory() as session:
        report = RepairReport(
            college_id=other_college.id,
            device_id=other_device.id,
            reporter_id=other_student.id,
            title="No manager assigned",
            description="Fallback recipient path",
            image_urls=None,
            status="PENDING",
            priority="NORMAL",
            response_due_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1),
            created_at=datetime.now(UTC).replace(tzinfo=None),
            updated_at=datetime.now(UTC).replace(tzinfo=None),
        )
        session.add(report)
        await session.commit()
        report_id = report.id
    await worker._handle(
        "REPAIR_SLA_REMINDER",
        {"report_id": report_id, "kind": "response"},
        task_key="coverage:repair:sla:no-manager",
    )
    async with factory() as session:
        generated = await session.scalar(
            select(OutboxTask).where(
                OutboxTask.task_key.like(f"notification:repair:{report_id}:sla:%")
            )
        )
        assert generated is None


@pytest.mark.asyncio
async def test_worker_repair_sla_ignores_missing_device_lookup(seeded, monkeypatch) -> None:
    factory, college, _, student, _, _, device, _ = seeded
    async with factory() as session:
        report = RepairReport(
            college_id=college.id,
            device_id=device.id,
            reporter_id=student.id,
            title="Device lookup race",
            description="The device lookup returns no row",
            image_urls=None,
            status="PENDING",
            priority="NORMAL",
            response_due_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1),
            created_at=datetime.now(UTC).replace(tzinfo=None),
            updated_at=datetime.now(UTC).replace(tzinfo=None),
        )
        session.add(report)
        await session.commit()
        report_id = report.id

    original_execute = AsyncSession.execute

    async def hide_device_info(session, statement, *args, **kwargs):
        query = str(statement).lower()
        if "device.name" in query and "lab.manager_id" in query:
            return SimpleNamespace(one_or_none=lambda: None)
        return await original_execute(session, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", hide_device_info)
    await OutboxWorker(_app(factory))._handle(
        "REPAIR_SLA_REMINDER",
        {"report_id": report_id, "kind": "response"},
    )


@pytest.mark.asyncio
async def test_worker_no_show_missing_user_penalty_block_and_compare_set_race(
    seeded,
    monkeypatch,
) -> None:
    factory, _, _, student, _, _, device, _ = seeded
    worker = OutboxWorker(
        _app(factory, credit_block_threshold=95, credit_block_days=2)
    )
    await worker._handle("RESERVATION_NO_SHOW", {"reservation_id": 999999})

    student_principal = Principal(
        user_id=student.id,
        username=student.username,
        college_id=student.college_id,
        roles=("STUDENT",),
        token_type="access",
        token_id="worker-no-show",
        permissions=("reservation:create", "device:read"),
    )
    async with factory() as session:
        reservation = await ReservationService(session, student_principal).create(
            ReservationPlanRequest(
                device_id=device.id,
                start_date=datetime.now(UTC).date() + timedelta(days=3),
                end_date=datetime.now(UTC).date() + timedelta(days=3),
                purpose="worker credit block threshold",
            )
        )
        reservation_id = reservation.created[0].id
        retry_reservation = await ReservationService(session, student_principal).create(
            ReservationPlanRequest(
                device_id=device.id,
                start_date=datetime.now(UTC).date() + timedelta(days=4),
                end_date=datetime.now(UTC).date() + timedelta(days=4),
                purpose="worker compare-set race",
            )
        )
        retry_id = retry_reservation.created[0].id
        user = await session.get(User, student.id)
        assert user is not None
        user.credit_score = 1
        await session.commit()

    await worker._handle("RESERVATION_NO_SHOW", {"reservation_id": reservation_id})
    async with factory() as session:
        user = await session.get(User, student.id)
        assert user is not None and user.credit_score == 0
        assert user.booking_blocked_until is not None

    original_execute = AsyncSession.execute
    race_once = True

    async def lose_reservation_update(session, statement, *args, **kwargs):
        nonlocal race_once
        if race_once and getattr(statement, "is_update", False):
            race_once = False
            return SimpleNamespace(rowcount=0)
        return await original_execute(session, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", lose_reservation_update)
    await worker._handle("RESERVATION_NO_SHOW", {"reservation_id": retry_id})
    async with factory() as session:
        reservation = await session.get(Reservation, retry_id)
        assert reservation is not None and reservation.status == "APPROVED"


@pytest.mark.asyncio
async def test_waitlist_worker_stops_for_unavailable_occupied_blackout_and_existing_offer(
    seeded,
) -> None:
    factory, college, _, student, _, _, device, _ = seeded
    reservation_date = datetime.now(UTC).date() + timedelta(days=5)
    worker = OutboxWorker(_app(factory))
    async with factory() as session:
        stored_device = await session.get(Device, device.id)
        assert stored_device is not None
        stored_device.status = "MAINTENANCE"
        session.add(
            ReservationBlackout(
                scope_type="DEVICE",
                scope_id=device.id,
                blocked_date=reservation_date + timedelta(days=1),
                reason="inspection",
                active=True,
                created_by=student.id,
            )
        )
        session.add(
            ReservationWaitlist(
                device_id=device.id,
                college_id=college.id,
                user_id=student.id,
                reservation_date=reservation_date + timedelta(days=2),
                purpose="active offer remains held",
                status="OFFERED",
            )
        )
        await session.flush()
        entry = await session.scalar(
            select(ReservationWaitlist).where(
                ReservationWaitlist.status == "OFFERED",
                ReservationWaitlist.device_id == device.id,
            )
        )
        assert entry is not None
        session.add(
            ReservationWaitlistOffer(
                waitlist_id=entry.id,
                device_id=device.id,
                college_id=college.id,
                user_id=student.id,
                reservation_date=entry.reservation_date,
                expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2),
            )
        )
        await session.commit()
        offer_date = entry.reservation_date
        await worker._handle(
            "WAITLIST_PROMOTE",
            {"device_id": device.id, "reservation_date": reservation_date.isoformat()},
        )
        stored_device.status = "IDLE"
        await session.commit()

    await worker._handle(
        "WAITLIST_PROMOTE",
        {"device_id": device.id, "reservation_date": reservation_date.isoformat()},
    )
    await worker._handle(
        "WAITLIST_PROMOTE",
        {
            "device_id": device.id,
            "reservation_date": (reservation_date + timedelta(days=1)).isoformat(),
        },
    )
    await worker._handle(
        "WAITLIST_PROMOTE",
        {"device_id": device.id, "reservation_date": offer_date.isoformat()},
    )
    await worker._handle("WAITLIST_OFFER_EXPIRE", {"waitlist_id": 999999})
    await worker._handle("WAITLIST_OFFER_EXPIRE", {"waitlist_id": entry.id})
    await worker._handle(
        "WAITLIST_PROMOTE",
        {"device_id": 999999, "reservation_date": reservation_date.isoformat()},
    )


@pytest.mark.asyncio
async def test_waitlist_worker_skips_past_safety_qualification_and_policy_ineligible_users(
    seeded,
    monkeypatch,
) -> None:
    factory, college, _, student, other_student, _, device, _ = seeded
    worker = OutboxWorker(_app(factory))
    today = datetime.now(UTC).date()

    async with factory() as session:
        past_entry = ReservationWaitlist(
            device_id=device.id,
            college_id=college.id,
            user_id=student.id,
            reservation_date=today - timedelta(days=1),
            purpose="past queue item",
            status="WAITING",
        )
        session.add(past_entry)
        session.add(
            ReservationWaitlist(
                device_id=device.id,
                college_id=college.id,
                user_id=other_student.id,
                reservation_date=today + timedelta(days=6),
                purpose="different college user",
                status="WAITING",
            )
        )
        blocked_user = User(
            username="waitlist-blocked-user",
            password_hash="test",
            real_name="Blocked waiter",
            college_id=college.id,
            status=1,
            booking_blocked_until=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=2),
        )
        session.add(blocked_user)
        await session.flush()
        session.add(
            ReservationWaitlist(
                device_id=device.id,
                college_id=college.id,
                user_id=blocked_user.id,
                reservation_date=today + timedelta(days=7),
                purpose="credit blocked user",
                status="WAITING",
            )
        )
        session.add(
            ReservationWaitlist(
                device_id=device.id,
                college_id=college.id,
                user_id=student.id,
                reservation_date=today + timedelta(days=8),
                purpose="needs safety acknowledgement",
                status="WAITING",
            )
        )
        await session.commit()
        stored_device = await session.get(Device, device.id)
        assert stored_device is not None
        stored_device.requires_safety_ack = True
        await session.commit()

    await worker._handle(
        "WAITLIST_PROMOTE",
        {"device_id": device.id, "reservation_date": (today - timedelta(days=1)).isoformat()},
    )
    await worker._handle(
        "WAITLIST_PROMOTE",
        {"device_id": device.id, "reservation_date": (today + timedelta(days=6)).isoformat()},
    )
    await worker._handle(
        "WAITLIST_PROMOTE",
        {"device_id": device.id, "reservation_date": (today + timedelta(days=7)).isoformat()},
    )
    await worker._handle(
        "WAITLIST_PROMOTE",
        {"device_id": device.id, "reservation_date": (today + timedelta(days=8)).isoformat()},
    )

    async with factory() as session:
        stored_device = await session.get(Device, device.id)
        assert stored_device is not None
        stored_device.requires_safety_ack = False
        stored_device.requires_qualification = True
        session.add(
            ReservationWaitlist(
                device_id=device.id,
                college_id=college.id,
                user_id=student.id,
                reservation_date=today + timedelta(days=9),
                purpose="requires qualification",
                status="WAITING",
            )
        )
        session.add(
            ReservationWaitlist(
                device_id=device.id,
                college_id=college.id,
                user_id=student.id,
                reservation_date=today + timedelta(days=365),
                purpose="date outside policy",
                status="WAITING",
            )
        )
        await session.commit()

    await worker._handle(
        "WAITLIST_PROMOTE",
        {"device_id": device.id, "reservation_date": (today + timedelta(days=9)).isoformat()},
    )
    await worker._handle(
        "WAITLIST_PROMOTE",
        {"device_id": device.id, "reservation_date": (today + timedelta(days=365)).isoformat()},
    )

    async with factory() as session:
        for offset in (6, 7, 8, 9, 365):
            entry = await session.scalar(
                select(ReservationWaitlist).where(
                    ReservationWaitlist.device_id == device.id,
                    ReservationWaitlist.reservation_date == today + timedelta(days=offset),
                )
            )
            assert entry is not None and entry.status == "SKIPPED", f"offset {offset}"

    monkeypatch.setattr(
        ReservationService,
        "preflight",
        AsyncMock(
            return_value=SimpleNamespace(
                conflicts=[SimpleNamespace(reason="concurrent reservation")],
                available_dates=[],
                safety_required=False,
                safety_acknowledged=True,
                qualification_required=False,
                qualification_approved=True,
            )
        ),
    )
    async with factory() as session:
        stored_device = await session.get(Device, device.id)
        assert stored_device is not None
        stored_device.requires_qualification = False
        await session.commit()
        session.add(
            ReservationWaitlist(
                device_id=device.id,
                college_id=college.id,
                user_id=student.id,
                reservation_date=today + timedelta(days=10),
                purpose="concurrent conflict in final preflight",
                status="WAITING",
            )
        )
        await session.commit()
    await worker._handle(
        "WAITLIST_PROMOTE",
        {"device_id": device.id, "reservation_date": (today + timedelta(days=10)).isoformat()},
    )


@pytest.mark.asyncio
async def test_waitlist_worker_drains_bounded_batch_of_ineligible_entries(seeded) -> None:
    factory, college, _, student, _, _, device, _ = seeded
    target_date = datetime.now(UTC).date() + timedelta(days=12)
    async with factory() as session:
        student_role = await session.scalar(select(Role).where(Role.role_code == "STUDENT"))
        assert student_role is not None
        users = [
            User(
                username=f"disabled-waiter-{index:03}",
                password_hash="test",
                real_name=f"Disabled waiter {index}",
                college_id=college.id,
                status=0,
                roles=[student_role],
            )
            for index in range(100)
        ]
        session.add_all(users)
        await session.flush()
        session.add_all(
            [
                ReservationWaitlist(
                    device_id=device.id,
                    college_id=college.id,
                    user_id=user.id,
                    reservation_date=target_date,
                    purpose="disabled account in queue",
                    status="WAITING",
                )
                for user in users
            ]
        )
        await session.commit()

    worker = OutboxWorker(_app(factory))
    await worker._handle(
        "WAITLIST_PROMOTE",
        {"device_id": device.id, "reservation_date": target_date.isoformat()},
    )
    async with factory() as session:
        skipped = int(
            await session.scalar(
                select(func.count(ReservationWaitlist.id)).where(
                    ReservationWaitlist.device_id == device.id,
                    ReservationWaitlist.reservation_date == target_date,
                    ReservationWaitlist.status == "SKIPPED",
                )
            )
            or 0
        )
        continuation = await session.scalar(
            select(OutboxTask).where(
                OutboxTask.task_type == "WAITLIST_PROMOTE",
                OutboxTask.task_key.like("waitlist:promote:continue:%"),
            )
        )
        assert skipped == 100
        assert continuation is not None


@pytest.mark.asyncio
async def test_worker_lazy_session_factory_initialization(seeded, monkeypatch) -> None:
    factory, *_ = seeded
    app = _app(factory)
    del app.state.session_factory
    engine = object()
    built_factory = object()
    metrics = SimpleNamespace(monitor_sqlalchemy_pool=Mock())
    app.state.metrics = metrics
    monkeypatch.setattr("app.infrastructure.db.session.build_engine", lambda _settings: engine)
    monkeypatch.setattr(worker_module, "build_session_factory", lambda value: built_factory)
    result = await OutboxWorker(app)._session_factory()
    assert result is built_factory
    assert app.state.db_engine is engine
    metrics.monitor_sqlalchemy_pool.assert_called_once_with(engine)

    no_metrics_app = _app(factory)
    del no_metrics_app.state.session_factory
    assert await OutboxWorker(no_metrics_app)._session_factory() is built_factory


@pytest.mark.asyncio
async def test_worker_repairs_auto_close_successful_resolved_report(seeded) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    async with factory() as session:
        report = await RepairService(session, _principal(student, "STUDENT")).create(
            device_id=device.id,
            title="worker auto close",
            description="automatic closure coverage",
            image_urls=None,
        )
    async with factory() as session:
        service = RepairService(session, _principal(manager, "LAB_ADMIN"))
        await service.take(report.id)
        await service.resolve(report.id, "已完成维修")
        task = await session.scalar(
            select(OutboxTask).where(OutboxTask.task_key == f"repair:{report.id}:auto-close")
        )
        assert task is not None
        task.status = "PROCESSING"
        task.execute_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        await session.commit()

    worker = OutboxWorker(_app(factory))
    task_key = f"repair:{report.id}:auto-close"
    await worker._handle("REPAIR_AUTO_CLOSE", {"report_id": report.id}, task_key=task_key)

    async with factory() as session:
        updated = await session.get(RepairReport, report.id)
        stored_device = await session.get(Device, device.id)
        worklog = await session.scalar(
            select(RepairWorklog).where(
                RepairWorklog.report_id == report.id,
                RepairWorklog.status == "COMPLETED",
            )
        )
        notice = await session.scalar(
            select(OutboxTask).where(
                OutboxTask.task_key == f"notification:repair:{report.id}:auto-closed"
            )
        )
        assert updated is not None and updated.status == "COMPLETED"
        assert stored_device is not None and stored_device.status == "IDLE"
        assert worklog is not None and notice is not None


@pytest.mark.asyncio
async def test_worker_auto_close_stale_key_missing_report_and_compare_set_race(
    seeded,
    monkeypatch,
) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    worker = OutboxWorker(_app(factory))
    await worker._handle("REPAIR_AUTO_CLOSE", {"report_id": 999999}, task_key=None)

    async with factory() as session:
        report = await RepairService(session, _principal(student, "STUDENT")).create(
            device_id=device.id,
            title="missing report reference",
            description="coverage test",
            image_urls=None,
        )
        report_id = report.id
    task_key = f"coverage:auto-close:missing-report:{report_id}"
    async with factory() as session:
        session.add(
            OutboxTask(
                task_key=task_key,
                task_type="REPAIR_AUTO_CLOSE",
                aggregate_key=f"repair:{report_id}",
                college_id=student.college_id,
                payload={"report_id": 999999},
                status="PROCESSING",
                attempts=1,
                claimed_at=datetime.now(UTC).replace(tzinfo=None),
                execute_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1),
            )
        )
        await session.commit()
    await worker._handle("REPAIR_AUTO_CLOSE", {"report_id": 999999}, task_key=task_key)

    async with factory() as session:
        service = RepairService(session, _principal(manager, "LAB_ADMIN"))
        await service.take(report_id)
        await service.resolve(report_id, "ready for compare-and-set race")
        task_key = f"repair:{report_id}:auto-close"
        task = await session.scalar(select(OutboxTask).where(OutboxTask.task_key == task_key))
        assert task is not None
        task.status = "PROCESSING"
        task.execute_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        await session.commit()

    original_execute = AsyncSession.execute

    async def lose_auto_close_race(session, statement, *args, **kwargs):
        if getattr(statement, "is_update", False):
            return SimpleNamespace(rowcount=0)
        return await original_execute(session, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", lose_auto_close_race)
    await worker._handle("REPAIR_AUTO_CLOSE", {"report_id": report_id}, task_key=task_key)
    async with factory() as session:
        report = await session.get(RepairReport, report_id)
        assert report is not None and report.status == "RESOLVED"


@pytest.mark.asyncio
async def test_worker_auto_close_keeps_device_maintenance_for_other_open_report(seeded) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    async with factory() as session:
        service = RepairService(session, _principal(student, "STUDENT"))
        first = await service.create(
            device_id=device.id,
            title="first open report",
            description=None,
            image_urls=None,
        )
        await service.create(
            device_id=device.id,
            title="second open report",
            description=None,
            image_urls=None,
        )
    async with factory() as session:
        service = RepairService(session, _principal(manager, "LAB_ADMIN"))
        await service.take(first.id)
        await service.resolve(first.id, "first repair complete")
        task_key = f"repair:{first.id}:auto-close"
        task = await session.scalar(select(OutboxTask).where(OutboxTask.task_key == task_key))
        assert task is not None
        task.status = "PROCESSING"
        task.execute_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        await session.commit()

    await OutboxWorker(_app(factory))._handle(
        "REPAIR_AUTO_CLOSE",
        {"report_id": first.id},
        task_key=task_key,
    )
    async with factory() as session:
        stored_device = await session.get(Device, device.id)
        assert stored_device is not None and stored_device.status == "MAINTENANCE"


@pytest.mark.asyncio
async def test_worker_export_generates_empty_and_large_csv_batches(
    seeded,
    tmp_path,
    monkeypatch,
) -> None:
    factory, college, _, student, *_ = seeded
    async with factory() as session:
        large = ExportTask(
            requester_id=student.id,
            college_id=college.id,
            export_type="RESERVATIONS",
            filters={"count": 501},
            status="PENDING",
        )
        empty = ExportTask(
            requester_id=student.id,
            college_id=college.id,
            export_type="RESERVATIONS",
            filters={"count": 0},
            status="PENDING",
        )
        session.add_all([large, empty])
        await session.commit()
        large_id, empty_id = large.id, empty.id

    async def rows(_session, _principal, _export_type, filters):
        for index in range(int(filters["count"])):
            yield {"id": index, "label": f"row-{index}"}

    monkeypatch.setattr(worker_module, "iter_export_rows", rows)
    worker = OutboxWorker(_app(factory, upload_dir=tmp_path))
    await worker._handle("EXPORT_GENERATE", {"export_id": large_id})
    await worker._handle("EXPORT_GENERATE", {"export_id": empty_id})

    async with factory() as session:
        large = await session.get(ExportTask, large_id)
        empty = await session.get(ExportTask, empty_id)
        assert large is not None and large.status == "COMPLETED" and large.row_count == 501
        assert empty is not None and empty.status == "COMPLETED" and empty.row_count == 0
        large_csv = Path(large.file_path or "").read_text(encoding="utf-8-sig")
        empty_csv = Path(empty.file_path or "").read_text(encoding="utf-8-sig")
        assert large_csv.count("id,label") == 1
        assert "row-500" in large_csv
        assert empty_csv == "暂无数据\n"


@pytest.mark.asyncio
async def test_worker_export_failure_marks_task_failed_and_reraises(
    seeded,
    tmp_path,
    monkeypatch,
) -> None:
    factory, college, _, student, *_ = seeded
    async with factory() as session:
        task = ExportTask(
            requester_id=student.id,
            college_id=college.id,
            export_type="RESERVATIONS",
            filters={},
            status="PENDING",
        )
        session.add(task)
        await session.commit()
        task_id = task.id

    async def fail_rows(*_args, **_kwargs):
        if False:
            yield {}
        raise RuntimeError("export source failed")

    monkeypatch.setattr(worker_module, "iter_export_rows", fail_rows)
    worker = OutboxWorker(_app(factory, upload_dir=tmp_path))
    with pytest.raises(RuntimeError, match="export source failed"):
        await worker._handle("EXPORT_GENERATE", {"export_id": task_id})
    async with factory() as session:
        stored = await session.get(ExportTask, task_id)
        assert stored is not None and stored.status == "FAILED"
        assert stored.error == "export source failed"


@pytest.mark.asyncio
async def test_worker_export_handles_deleted_task_missing_requester_and_failed_reread(
    tmp_path,
    monkeypatch,
) -> None:
    class ScriptedSession:
        def __init__(self, results):
            self.results = iter(results)
            self.add = Mock()
            self.commit = AsyncMock()
            self.rollback = AsyncMock()

        def __call__(self):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def scalar(self, _statement):
            return next(self.results)

    async def run_script(results, *, export_id=91):
        session = ScriptedSession(results)
        app = FastAPI()
        app.state.settings = Settings(
            environment="test",
            cors_origins=[],
            enable_workers=False,
            upload_dir=str(tmp_path),
        )
        app.state.session_factory = session
        await OutboxWorker(app)._handle("EXPORT_GENERATE", {"export_id": export_id})
        return session

    assert (await run_script([None])).commit.await_count == 0
    completed = SimpleNamespace(id=92, status="COMPLETED")
    assert (await run_script([completed])).commit.await_count == 0

    missing_again = SimpleNamespace(id=93, status="PENDING", updated_at=None)
    session = await run_script([missing_again, None], export_id=93)
    assert session.commit.await_count == 1

    missing_requester = SimpleNamespace(
        id=94,
        status="PENDING",
        updated_at=None,
        requester_id=999,
    )
    session = await run_script(
        [missing_requester, missing_requester, None],
        export_id=94,
    )
    assert missing_requester.status == "FAILED"
    assert missing_requester.error
    assert session.commit.await_count == 2

    failed_reread = SimpleNamespace(
        id=95,
        status="PENDING",
        updated_at=None,
        requester_id=95,
        college_id=None,
        export_type="RESERVATIONS",
        filters={},
    )

    async def fail_before_rows(*_args, **_kwargs):
        if False:
            yield {}
        raise RuntimeError("task removed during export")

    monkeypatch.setattr(worker_module, "iter_export_rows", fail_before_rows)
    export_user = SimpleNamespace(id=95, username="export-user", college_id=None, roles=[])
    session = ScriptedSession([failed_reread, failed_reread, export_user, None])
    app = FastAPI()
    app.state.settings = Settings(
        environment="test",
        cors_origins=[],
        enable_workers=False,
        upload_dir=str(tmp_path),
    )
    app.state.session_factory = session
    with pytest.raises(RuntimeError, match="task removed during export"):
        await OutboxWorker(app)._handle("EXPORT_GENERATE", {"export_id": 95})
    session.rollback.assert_awaited_once()
    assert session.commit.await_count == 1


@pytest.mark.asyncio
async def test_worker_cache_bump_and_unknown_task(seeded, monkeypatch) -> None:
    factory, *_ = seeded
    cache = SimpleNamespace(bump_version=AsyncMock())
    monkeypatch.setattr(worker_module, "get_redis_for_app", lambda _app: "redis")
    monkeypatch.setattr(worker_module, "get_redis_circuit", lambda _app: "circuit")
    monkeypatch.setattr(worker_module, "CacheService", lambda *_args: cache)
    worker = OutboxWorker(_app(factory))
    await worker._handle("CACHE_BUMP", {"scope": "college:7"})
    cache.bump_version.assert_awaited_once_with("college:7")
    with pytest.raises(ValueError, match="unsupported outbox task type"):
        await worker._handle("UNSUPPORTED", {})
