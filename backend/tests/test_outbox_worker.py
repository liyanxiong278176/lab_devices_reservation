import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest
from app.api.v2.schemas import ReservationPlanRequest
from app.application.repairs import RepairService
from app.application.reservations import ReservationService
from app.auth.security import Principal
from app.core.settings import Settings
from app.infrastructure.db.models import (
    CreditEvent,
    DeviceHandover,
    DeviceMaintenancePlan,
    Notification,
    OutboxTask,
    RepairReport,
    RepairWorklog,
    Reservation,
    ReservationItem,
    ReservationWaitlist,
    ReservationWaitlistOffer,
    Role,
    UploadAsset,
    User,
)
from app.infrastructure.tasks.worker import OutboxWorker
from fastapi import FastAPI
from sqlalchemy import func, select, update


def principal(user: User, *roles: str) -> Principal:
    permission_map = {
        "STUDENT": (
            "device:read", "reservation:create", "reservation:read:own", "reservation:cancel",
            "reservation:check-in", "reservation:return", "repair:create",
            "repair:read:own", "repair:confirm",
        ),
        "LAB_ADMIN": (
            "device:read", "device:manage", "reservation:read:scope", "reservation:approve",
            "reservation:handover", "reservation:accept-return", "repair:read:scope",
            "repair:handle", "report:read", "maintenance:manage",
            "reservation-rule:manage",
        ),
    }
    return Principal(
        user_id=user.id,
        username=user.username,
        college_id=user.college_id,
        roles=roles,
        token_type="access",
        token_id="worker-test-token",
        permissions=tuple({code for role in roles for code in permission_map.get(role, ())}),
    )


async def add_evidence(session, user: User, token: str) -> str:
    session.add(
        UploadAsset(
            asset_token=token,
            user_id=user.id,
            college_id=user.college_id,
            original_name="handover-evidence.png",
            content_type="image/png",
            size_bytes=128,
            storage_path=f"memory://{token}",
        )
    )
    await session.flush()
    return f"/api/v2/repair-uploads/{token}"


@pytest.mark.asyncio
async def test_outbox_notification_is_processed_and_completed(seeded) -> None:
    factory, _, _, student1, _, _, _, _ = seeded
    app = FastAPI()
    app.state.settings = Settings(environment="test", cors_origins=[], enable_workers=False)
    app.state.session_factory = factory
    worker = OutboxWorker(app, poll_seconds=0.01)
    async with factory() as session:
        session.add(
            OutboxTask(
                task_key="test:notification:001",
                task_type="NOTIFICATION",
                college_id=student1.college_id,
                payload={
                    "user_id": student1.id,
                    "college_id": student1.college_id,
                    "title": "测试通知",
                    "content": "任务可重试且可持久化",
                },
                execute_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        await session.commit()

    assert await worker.run_once() is True

    async with factory() as session:
        task = await session.scalar(
            select(OutboxTask).where(OutboxTask.task_key == "test:notification:001")
        )
        notification = await session.scalar(
            select(Notification).where(Notification.user_id == student1.id)
        )
        assert task is not None and task.status == "COMPLETED"
        assert notification is not None and notification.content == "任务可重试且可持久化"


@pytest.mark.asyncio
async def test_outbox_worker_retries_poll_after_transient_database_failure(
    seeded,
    monkeypatch,
) -> None:
    factory, _, _, _, _, _, _, _ = seeded
    app = FastAPI()
    app.state.settings = Settings(environment="test", cors_origins=[], enable_workers=False)
    app.state.session_factory = factory
    worker = OutboxWorker(app, poll_seconds=0.01)
    poll_recovered = asyncio.Event()
    attempts = 0

    async def fail_once_then_report_empty():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionError("temporary database outage")
        poll_recovered.set()
        return None

    monkeypatch.setattr(worker, "_claim_one", fail_once_then_report_empty)
    started = asyncio.get_running_loop().time()
    task = asyncio.create_task(worker._run())
    await asyncio.wait_for(poll_recovered.wait(), timeout=1)
    assert asyncio.get_running_loop().time() - started >= 0.08
    worker._stop.set()
    await asyncio.wait_for(task, timeout=1)

    assert attempts >= 2


@pytest.mark.asyncio
async def test_handover_fault_timeout_cancels_without_no_show_penalty(seeded) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    day = date.today()
    async with factory() as session:
        created = await ReservationService(
            session,
            principal(student, "STUDENT"),
        ).create(
            ReservationPlanRequest(
                device_id=device.id,
                start_date=day,
                end_date=day,
                purpose="异常交接超时不扣信用",
            )
        )
        reservation_id = created.created[0].id
        image = await add_evidence(session, manager, "worker-handover-exception-0001")
        await ReservationService(session, principal(manager, "LAB_ADMIN")).handover(
            reservation_id,
            condition="DAMAGED",
            note="交接时发现设备损坏",
            image_urls=[image],
        )
        credit_before = student.credit_score

    app = FastAPI()
    app.state.settings = Settings(environment="test", cors_origins=[], enable_workers=False)
    app.state.session_factory = factory
    await OutboxWorker(app)._handle(
        "RESERVATION_NO_SHOW",
        {"reservation_id": reservation_id, "user_id": student.id, "college_id": student.college_id},
        task_key=f"timeout:reservation:{reservation_id}:no-show",
    )

    async with factory() as session:
        reservation = await session.get(Reservation, reservation_id)
        user = await session.get(User, student.id)
        handover = await session.scalar(
            select(DeviceHandover).where(DeviceHandover.reservation_id == reservation_id)
        )
        repair = await session.scalar(
            select(RepairReport).where(RepairReport.reservation_id == reservation_id)
        )
        occupancy_count = int(
            await session.scalar(
                select(func.count(ReservationItem.id)).where(
                    ReservationItem.reservation_id == reservation_id
                )
            )
            or 0
        )
        penalty_count = int(
            await session.scalar(
                select(func.count(CreditEvent.id)).where(
                    CreditEvent.reservation_id == reservation_id,
                    CreditEvent.event_type == "NO_SHOW",
                )
            )
            or 0
        )
        notice = await session.scalar(
            select(OutboxTask).where(
                OutboxTask.task_key
                == f"notification:reservation:{reservation_id}:handover-exception-auto-cancel"
            )
        )
        assert reservation is not None and reservation.status == "CANCELLED"
        assert reservation.handover_status == "CANCELLED"
        assert user is not None and user.credit_score == credit_before
        assert handover is not None and handover.status == "CANCELLED"
        assert repair is not None and repair.status == "PENDING"
        assert occupancy_count == 0
        assert penalty_count == 0
        assert notice is not None and "未扣除信用分" in notice.payload["content"]


@pytest.mark.asyncio
async def test_pending_handover_timeout_still_records_no_show_penalty(seeded) -> None:
    factory, _, _, student, _, _, device, _ = seeded
    day = date.today()
    async with factory() as session:
        created = await ReservationService(
            session,
            principal(student, "STUDENT"),
        ).create(
            ReservationPlanRequest(
                device_id=device.id,
                start_date=day,
                end_date=day,
                purpose="待交接超时记录爽约",
            )
        )
        reservation_id = created.created[0].id
        credit_before = student.credit_score

    app = FastAPI()
    app.state.settings = Settings(environment="test", cors_origins=[], enable_workers=False)
    app.state.session_factory = factory
    await OutboxWorker(app)._handle(
        "RESERVATION_NO_SHOW",
        {"reservation_id": reservation_id, "user_id": student.id, "college_id": student.college_id},
        task_key=f"timeout:reservation:{reservation_id}:no-show",
    )

    async with factory() as session:
        reservation = await session.get(Reservation, reservation_id)
        user = await session.get(User, student.id)
        penalty_count = int(
            await session.scalar(
                select(func.count(CreditEvent.id)).where(
                    CreditEvent.reservation_id == reservation_id,
                    CreditEvent.event_type == "NO_SHOW",
                )
            )
            or 0
        )
        assert reservation is not None and reservation.status == "NO_SHOW"
        assert user is not None and user.credit_score == credit_before - 10
        assert penalty_count == 1


@pytest.mark.asyncio
async def test_repair_sla_reminder_notifies_responsible_manager_idempotently(seeded) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    report_principal = principal(student, "STUDENT")
    manager_principal = principal(manager, "LAB_ADMIN")
    async with factory() as session:
        report = await RepairService(session, report_principal).create(
            device_id=device.id,
            title="SLA 超时回归测试",
            description="测试负责人超时提醒",
            image_urls=None,
        )
    async with factory() as session:
        await RepairService(session, manager_principal).take(report.id)
        await session.execute(
            update(RepairReport)
            .where(RepairReport.id == report.id)
            .values(resolve_due_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1))
        )
        await session.commit()

    app = FastAPI()
    app.state.settings = Settings(environment="test", cors_origins=[], enable_workers=False)
    app.state.session_factory = factory
    worker = OutboxWorker(app, poll_seconds=0.01)
    task_key = f"repair:{report.id}:sla-resolve"
    payload = {"report_id": report.id, "kind": "resolve"}

    await worker._handle("REPAIR_SLA_REMINDER", payload, task_key=task_key)
    await worker._handle("REPAIR_SLA_REMINDER", payload, task_key=task_key)

    notification_task_key = f"notification:repair:{report.id}:sla:resolve:user:{manager.id}"
    async with factory() as session:
        notification_task = await session.scalar(
            select(OutboxTask).where(OutboxTask.task_key == notification_task_key)
        )
        assert notification_task is not None
        assert notification_task.payload["title"] == "报修处理已超时"
        assert notification_task.payload["user_id"] == manager.id

    await worker._handle(
        "NOTIFICATION",
        notification_task.payload,
        task_key=notification_task_key,
    )
    await worker._handle(
        "NOTIFICATION",
        notification_task.payload,
        task_key=notification_task_key,
    )

    async with factory() as session:
        task_count = await session.scalar(
            select(func.count(OutboxTask.id)).where(OutboxTask.task_key == notification_task_key)
        )
        notification_count = await session.scalar(
            select(func.count(Notification.id)).where(
                Notification.source_task_key == notification_task_key
            )
        )
        assert task_count == 1
        assert notification_count == 1


@pytest.mark.asyncio
async def test_repair_sla_reminder_ignores_stale_or_not_yet_due_reports(seeded) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    async with factory() as session:
        report = await RepairService(session, principal(student, "STUDENT")).create(
            device_id=device.id,
            title="过期 SLA 任务回归测试",
            description="状态变化后不应再发旧提醒",
            image_urls=None,
        )
    async with factory() as session:
        await RepairService(session, principal(manager, "LAB_ADMIN")).take(report.id)
        await session.execute(
            update(RepairReport)
            .where(RepairReport.id == report.id)
            .values(
                response_due_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1),
                resolve_due_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1),
            )
        )
        await session.commit()

    app = FastAPI()
    app.state.settings = Settings(environment="test", cors_origins=[], enable_workers=False)
    app.state.session_factory = factory
    worker = OutboxWorker(app, poll_seconds=0.01)
    await worker._handle(
        "REPAIR_SLA_REMINDER",
        {"report_id": report.id, "kind": "response"},
        task_key=f"repair:{report.id}:sla-response",
    )
    await worker._handle(
        "REPAIR_SLA_REMINDER",
        {"report_id": report.id, "kind": "resolve"},
        task_key=f"repair:{report.id}:sla-resolve",
    )

    async with factory() as session:
        reminders = await session.scalar(
            select(func.count(OutboxTask.id)).where(
                OutboxTask.task_key.like(f"notification:repair:{report.id}:sla:%")
            )
        )
        assert reminders == 0


@pytest.mark.asyncio
async def test_stale_processing_task_is_reclaimed_after_worker_restart(seeded) -> None:
    factory, _, _, student1, _, _, _, _ = seeded
    app = FastAPI()
    app.state.settings = Settings(
        environment="test",
        cors_origins=[],
        enable_workers=False,
        outbox_claim_timeout_seconds=1,
    )
    app.state.session_factory = factory
    worker = OutboxWorker(app, poll_seconds=0.01)
    async with factory() as session:
        session.add(
            OutboxTask(
                task_key="test:notification:stale-001",
                task_type="NOTIFICATION",
                college_id=student1.college_id,
                payload={
                    "user_id": student1.id,
                    "college_id": student1.college_id,
                    "title": "恢复任务",
                    "content": "进程重启后继续处理",
                },
                status="PROCESSING",
                attempts=1,
                claimed_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=5),
                execute_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        await session.commit()

    assert await worker.run_once() is True
    async with factory() as session:
        task = await session.scalar(
            select(OutboxTask).where(OutboxTask.task_key == "test:notification:stale-001")
        )
        notification = await session.scalar(
            select(Notification).where(Notification.title == "恢复任务")
        )
        assert task is not None and task.status == "COMPLETED"
        assert notification is not None


@pytest.mark.asyncio
async def test_exhausted_stale_outbox_claim_is_terminally_failed(seeded) -> None:
    factory, _, _, student, _, _, _, _ = seeded
    app = FastAPI()
    app.state.settings = Settings(
        environment="test",
        cors_origins=[],
        enable_workers=False,
        outbox_claim_timeout_seconds=1,
        outbox_max_attempts=2,
    )
    app.state.session_factory = factory
    worker = OutboxWorker(app, poll_seconds=0.01)
    task_key = "test:notification:exhausted-stale-001"
    async with factory() as session:
        session.add(
            OutboxTask(
                task_key=task_key,
                task_type="NOTIFICATION",
                college_id=student.college_id,
                payload={"user_id": student.id, "title": "不应永久处理中", "content": ""},
                status="PROCESSING",
                attempts=2,
                claimed_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=5),
                execute_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        await session.commit()

    assert await worker._claim_one() is None
    async with factory() as session:
        task = await session.scalar(select(OutboxTask).where(OutboxTask.task_key == task_key))
        assert task is not None
        assert task.status == "FAILED"
        assert task.claimed_at is None
        assert "maximum of 2 attempts" in (task.last_error or "")


@pytest.mark.asyncio
async def test_stale_repair_auto_close_does_not_run_after_reopen_and_reschedule(seeded) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    student_principal = Principal(
        user_id=student.id,
        username=student.username,
        college_id=student.college_id,
        roles=("STUDENT",),
        token_type="access",
        token_id="student-test",
        permissions=("repair:create", "repair:read:own", "repair:confirm"),
    )
    manager_principal = Principal(
        user_id=manager.id,
        username=manager.username,
        college_id=manager.college_id,
        roles=("LAB_ADMIN",),
        token_type="access",
        token_id="manager-test",
        permissions=("repair:read:scope", "repair:handle"),
    )
    async with factory() as session:
        created = await RepairService(session, student_principal).create(
            device_id=device.id,
            title="维修后再次出现故障",
            description="回归测试",
            image_urls=None,
        )
    async with factory() as session:
        await RepairService(session, manager_principal).take(created.id)
    async with factory() as session:
        await RepairService(session, manager_principal).resolve(created.id, "初次维修完成")
    task_key = f"repair:{created.id}:auto-close"
    async with factory() as session:
        first_cycle_task = await session.scalar(
            select(OutboxTask).where(OutboxTask.task_key == task_key)
        )
        assert first_cycle_task is not None
        stale_payload = dict(first_cycle_task.payload)

    async with factory() as session:
        await RepairService(session, student_principal).confirm(
            created.id,
            confirmed=False,
            note="问题仍然存在",
        )
    async with factory() as session:
        await RepairService(session, manager_principal).resolve(created.id, "重新检修后完成处理")

    app = FastAPI()
    app.state.settings = Settings(environment="test", cors_origins=[], enable_workers=False)
    app.state.session_factory = factory
    worker = OutboxWorker(app, poll_seconds=0.01)
    await worker._handle(
        "REPAIR_AUTO_CLOSE",
        stale_payload,
        task_key=task_key,
    )

    async with factory() as session:
        report = await session.scalar(select(RepairReport).where(RepairReport.id == created.id))
        worklogs = list(
            (
                await session.scalars(
                    select(RepairWorklog).where(RepairWorklog.report_id == created.id)
                )
            ).all()
        )
    assert report is not None and report.status == "RESOLVED"
    assert all(worklog.status != "COMPLETED" for worklog in worklogs)
    async with factory() as session:
        current_task = await session.scalar(
            select(OutboxTask).where(OutboxTask.task_key == task_key)
        )
        assert current_task is not None
        assert current_task.status == "PENDING"
        assert current_task.execute_at > datetime.now(UTC).replace(tzinfo=None)


@pytest.mark.asyncio
async def test_waitlist_offer_holds_device_and_expiry_promotes_next_user(seeded) -> None:
    factory, college, _, first_user, _, _, device, _ = seeded
    device.need_approval = True
    reservation_date = date.today() + timedelta(days=4)
    async with factory() as session:
        session.add(device)
        student_role = await session.scalar(select(Role).where(Role.role_code == "STUDENT"))
        assert student_role is not None
        second_user = User(
            username="waitlist-second-user",
            password_hash="test",
            real_name="候补用户二",
            college_id=college.id,
            status=1,
            roles=[student_role],
        )
        session.add(second_user)
        await session.flush()
        second_user_id = second_user.id
        initial = await ReservationService(
            session,
            principal(first_user, "STUDENT"),
        ).create(
            ReservationPlanRequest(
                device_id=device.id,
                start_date=reservation_date,
                end_date=reservation_date,
                purpose="释放给候补的预约",
            )
        )
        first_waitlist = await ReservationService(
            session,
            principal(first_user, "STUDENT"),
        ).join_waitlist(
            device_id=device.id,
            reservation_date=reservation_date,
            purpose="候补用户一需求",
        )
        second_waitlist = await ReservationService(
            session,
            principal(second_user, "STUDENT"),
        ).join_waitlist(
            device_id=device.id,
            reservation_date=reservation_date,
            purpose="候补用户二需求",
        )
        await ReservationService(
            session,
            principal(first_user, "STUDENT"),
        ).cancel(initial.created[0].id)

    app = FastAPI()
    app.state.settings = Settings(environment="test", cors_origins=[], enable_workers=False)
    app.state.session_factory = factory
    worker = OutboxWorker(app, poll_seconds=0.01)
    payload = {"device_id": device.id, "reservation_date": reservation_date.isoformat()}
    await worker._handle("WAITLIST_PROMOTE", payload)

    async with factory() as session:
        first_entry = await session.get(ReservationWaitlist, first_waitlist.id)
        second_entry = await session.get(ReservationWaitlist, second_waitlist.id)
        offer = await session.scalar(
            select(ReservationWaitlistOffer).where(
                ReservationWaitlistOffer.waitlist_id == first_waitlist.id
            )
        )
        assert first_entry is not None and first_entry.status == "OFFERED"
        assert second_entry is not None and second_entry.status == "WAITING"
        assert offer is not None and offer.expires_at > datetime.now(UTC).replace(tzinfo=None)
        second_user = await session.get(User, second_user_id)
        assert second_user is not None
        preflight = await ReservationService(
            session,
            principal(second_user, "STUDENT"),
        ).preflight(
            ReservationPlanRequest(
                device_id=device.id,
                start_date=reservation_date,
                end_date=reservation_date,
                purpose="检查独占保留",
            )
        )
        assert preflight.conflicts[0].status == "WAITLIST_HOLD"
        offer.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        await session.commit()

    await worker._handle("WAITLIST_OFFER_EXPIRE", {"waitlist_id": first_waitlist.id})
    await worker._handle("WAITLIST_PROMOTE", payload)
    async with factory() as session:
        second_entry = await session.get(ReservationWaitlist, second_waitlist.id)
        assert second_entry is not None and second_entry.status == "OFFERED"

    async with factory() as session:
        second_user = await session.get(User, second_user_id)
        assert second_user is not None
        confirmed = await ReservationService(
            session,
            principal(second_user, "STUDENT"),
        ).confirm_waitlist_offer(second_waitlist.id)
        assert confirmed.reservation.status == "PENDING"
        assert confirmed.reservation.purpose == "候补用户二需求"
        saved_entry = await session.get(ReservationWaitlist, second_waitlist.id)
        saved_offer = await session.scalar(
            select(ReservationWaitlistOffer).where(
                ReservationWaitlistOffer.waitlist_id == second_waitlist.id
            )
        )
        saved_reservation = await session.get(Reservation, confirmed.reservation.id)
        assert saved_entry is not None and saved_entry.status == "CONFIRMED"
        assert saved_offer is None
        assert saved_reservation is not None and saved_reservation.status == "PENDING"


@pytest.mark.asyncio
async def test_waitlist_skips_ineligible_user_and_promotes_next_candidate(seeded) -> None:
    factory, college, _, first_user, _, _, device, _ = seeded
    requested_date = date.today() + timedelta(days=4)
    async with factory() as session:
        student_role = await session.scalar(select(Role).where(Role.role_code == "STUDENT"))
        assert student_role is not None
        second_user = User(
            username="waitlist-eligible-user",
            password_hash="test",
            real_name="候补用户二",
            college_id=college.id,
            status=1,
            roles=[student_role],
        )
        session.add(second_user)
        await session.flush()
        second_user_id = second_user.id
        reservation = await ReservationService(
            session,
            principal(first_user, "STUDENT"),
        ).create(
            ReservationPlanRequest(
                device_id=device.id,
                start_date=requested_date,
                end_date=requested_date,
                purpose="释放候补日期",
            )
        )
        first_entry = await ReservationService(
            session,
            principal(first_user, "STUDENT"),
        ).join_waitlist(
            device_id=device.id,
            reservation_date=requested_date,
            purpose="已失去预约资格的候补",
        )
        second_entry = await ReservationService(
            session,
            principal(second_user, "STUDENT"),
        ).join_waitlist(
            device_id=device.id,
            reservation_date=requested_date,
            purpose="下一位有效候补",
        )
        await ReservationService(
            session,
            principal(first_user, "STUDENT"),
        ).cancel(reservation.created[0].id)
        stored_user = await session.get(User, first_user.id)
        assert stored_user is not None
        stored_user.status = 0
        await session.commit()

    app = FastAPI()
    app.state.settings = Settings(environment="test", cors_origins=[], enable_workers=False)
    app.state.session_factory = factory
    await OutboxWorker(app)._handle(
        "WAITLIST_PROMOTE",
        {"device_id": device.id, "reservation_date": requested_date.isoformat()},
    )

    async with factory() as session:
        skipped = await session.get(ReservationWaitlist, first_entry.id)
        offered = await session.get(ReservationWaitlist, second_entry.id)
        offer = await session.scalar(
            select(ReservationWaitlistOffer).where(
                ReservationWaitlistOffer.waitlist_id == second_entry.id
            )
        )
        notification = await session.scalar(
            select(OutboxTask).where(
                OutboxTask.task_key
                == f"notification:waitlist:{first_entry.id}:ineligible:{requested_date.isoformat()}"
            )
        )
        assert skipped is not None and skipped.status == "SKIPPED"
        assert offered is not None and offered.user_id == second_user_id
        assert offered.status == "OFFERED"
        assert offer is not None
        assert notification is not None and "停用" in notification.payload["content"]


@pytest.mark.asyncio
async def test_waitlist_promotion_continues_after_one_hundred_ineligible_users(seeded) -> None:
    factory, college, _, _, _, _, device, _ = seeded
    requested_date = date.today() + timedelta(days=4)
    async with factory() as session:
        student_role = await session.scalar(select(Role).where(Role.role_code == "STUDENT"))
        assert student_role is not None
        inactive_users = [
            User(
                username=f"waitlist-ineligible-{index}",
                password_hash="test",
                real_name=f"停用候补用户{index}",
                college_id=college.id,
                status=0,
                roles=[student_role],
            )
            for index in range(101)
        ]
        eligible_user = User(
            username="waitlist-after-large-invalid-queue",
            password_hash="test",
            real_name="长队列后的有效候补",
            college_id=college.id,
            status=1,
            roles=[student_role],
        )
        session.add_all([*inactive_users, eligible_user])
        await session.flush()
        session.add_all(
            [
                ReservationWaitlist(
                    device_id=device.id,
                    college_id=college.id,
                    user_id=user.id,
                    reservation_date=requested_date,
                    purpose="长队列候补测试",
                    status="WAITING",
                )
                for user in [*inactive_users, eligible_user]
            ]
        )
        await session.commit()
        eligible_user_id = eligible_user.id

    app = FastAPI()
    app.state.settings = Settings(environment="test", cors_origins=[], enable_workers=False)
    app.state.session_factory = factory
    worker = OutboxWorker(app)
    payload = {"device_id": device.id, "reservation_date": requested_date.isoformat()}

    await worker._handle("WAITLIST_PROMOTE", payload)
    async with factory() as session:
        skipped_count = await session.scalar(
            select(func.count(ReservationWaitlist.id)).where(
                ReservationWaitlist.device_id == device.id,
                ReservationWaitlist.reservation_date == requested_date,
                ReservationWaitlist.status == "SKIPPED",
            )
        )
        continuation = await session.scalar(
            select(OutboxTask).where(
                OutboxTask.task_type == "WAITLIST_PROMOTE",
                OutboxTask.task_key.like("waitlist:promote:continue:%"),
            )
        )
        assert skipped_count == 100
        assert continuation is not None

    # A second worker pass represents the durable continuation task.
    await worker._handle("WAITLIST_PROMOTE", payload)
    async with factory() as session:
        eligible_entry = await session.scalar(
            select(ReservationWaitlist).where(
                ReservationWaitlist.user_id == eligible_user_id,
                ReservationWaitlist.device_id == device.id,
                ReservationWaitlist.reservation_date == requested_date,
            )
        )
        offer = await session.scalar(
            select(ReservationWaitlistOffer).where(
                ReservationWaitlistOffer.user_id == eligible_user_id,
                ReservationWaitlistOffer.device_id == device.id,
                ReservationWaitlistOffer.reservation_date == requested_date,
            )
        )
        assert eligible_entry is not None and eligible_entry.status == "OFFERED"
        assert offer is not None


@pytest.mark.asyncio
async def test_waitlist_promotion_skips_newly_maintenance_blocked_date(seeded) -> None:
    factory, _, _, user, _, manager, device, _ = seeded
    requested_date = date.today() + timedelta(days=4)
    async with factory() as session:
        reservation = await ReservationService(
            session,
            principal(user, "STUDENT"),
        ).create(
            ReservationPlanRequest(
                device_id=device.id,
                start_date=requested_date,
                end_date=requested_date,
                purpose="释放维护冲突候补日期",
            )
        )
        entry = await ReservationService(
            session,
            principal(user, "STUDENT"),
        ).join_waitlist(
            device_id=device.id,
            reservation_date=requested_date,
            purpose="维护到期前加入候补",
        )
        await ReservationService(session, principal(user, "STUDENT")).cancel(
            reservation.created[0].id
        )
        session.add(
            DeviceMaintenancePlan(
                device_id=device.id,
                college_id=device.college_id,
                plan_type="CALIBRATION",
                title="逾期校准",
                interval_value=1,
                interval_unit="YEAR",
                due_date=date.today() - timedelta(days=1),
                active=True,
                created_by=manager.id,
                updated_by=manager.id,
            )
        )
        await session.commit()

    app = FastAPI()
    app.state.settings = Settings(environment="test", cors_origins=[], enable_workers=False)
    app.state.session_factory = factory
    await OutboxWorker(app)._handle(
        "WAITLIST_PROMOTE",
        {"device_id": device.id, "reservation_date": requested_date.isoformat()},
    )

    async with factory() as session:
        skipped = await session.get(ReservationWaitlist, entry.id)
        offer = await session.scalar(
            select(ReservationWaitlistOffer).where(
                ReservationWaitlistOffer.waitlist_id == entry.id
            )
        )
        assert skipped is not None and skipped.status == "SKIPPED"
        assert offer is None
