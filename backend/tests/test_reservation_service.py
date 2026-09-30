from datetime import date, timedelta

import pytest
from app.api.v2.schemas import ReservationPlanRequest
from app.application.recommendations import RecommendationService
from app.application.reservations import ReservationService
from app.auth.security import Principal
from app.core.errors import ApiError
from app.infrastructure.db.models import (
    Device,
    DeviceCategory,
    DeviceHandover,
    DeviceQualification,
    OutboxTask,
    RepairReport,
    Reservation,
    ReservationItem,
    Role,
    UploadAsset,
    User,
)
from pydantic import ValidationError
from sqlalchemy import delete, func, select, update


def test_reservation_plan_rejects_huge_date_range_before_expansion() -> None:
    with pytest.raises(ValidationError, match="最多支持 31 个自然日"):
        ReservationPlanRequest(
            device_id=1,
            start_date=date(1, 1, 1),
            end_date=date(9999, 12, 31),
            purpose="超长区间输入",
        )


def test_reservation_plan_rejects_more_than_31_total_window_days() -> None:
    with pytest.raises(ValidationError, match="最多支持 31 个自然日"):
        ReservationPlanRequest(
            device_id=1,
            windows=[
                {"start_date": date(2026, 1, 1), "end_date": date(2026, 1, 20)},
                {"start_date": date(2026, 2, 1), "end_date": date(2026, 2, 13)},
            ],
            purpose="多窗口超限输入",
        )


def principal(user: User, *roles: str) -> Principal:
    permission_map = {
        "STUDENT": (
            "device:read",
            "reservation:create",
            "reservation:read:own",
            "reservation:cancel",
            "reservation:check-in",
            "reservation:return",
            "repair:create",
            "repair:read:own",
            "repair:confirm",
        ),
        "LAB_ADMIN": (
            "device:read",
            "device:manage",
            "reservation:read:scope",
            "reservation:approve",
            "reservation:handover",
            "reservation:accept-return",
            "repair:read:scope",
            "repair:handle",
            "report:read",
            "maintenance:manage",
            "reservation-rule:manage",
        ),
    }
    return Principal(
        user_id=user.id,
        username=user.username,
        college_id=user.college_id,
        roles=roles,
        token_type="access",
        token_id="test-token",
        permissions=tuple({code for role in roles for code in permission_map.get(role, ())}),
    )


async def add_evidence(session, user: User, token: str) -> str:
    session.add(
        UploadAsset(
            asset_token=token,
            user_id=user.id,
            college_id=user.college_id,
            original_name="evidence.png",
            content_type="image/png",
            size_bytes=128,
            storage_path=f"memory://{token}",
        )
    )
    await session.flush()
    return f"/api/v2/repair-uploads/{token}"


@pytest.mark.asyncio
async def test_college_isolation_and_idempotent_reservation(seeded) -> None:
    factory, _, _, student1, student2, _, device, _ = seeded
    target = date.today() + timedelta(days=2)
    plan = ReservationPlanRequest(
        device_id=device.id,
        start_date=target,
        end_date=target + timedelta(days=1),
        purpose="模型训练",
    )

    async with factory() as session:
        service = ReservationService(session, principal(student1, "STUDENT"))
        first = await service.create(plan, idempotency_key="reservation-test-001")
        replay = await service.create(plan, idempotency_key="reservation-test-001")
        assert [row.id for row in first.created] == [row.id for row in replay.created]
        assert len(first.created[0].dates) == 2
        legacy_row = await session.scalar(
            select(Reservation).where(Reservation.id == first.created[0].id)
        )
        assert legacy_row is not None
        assert legacy_row.start_time is not None
        assert legacy_row.end_time is not None

    async with factory() as session:
        hidden = ReservationService(session, principal(student2, "STUDENT"))
        items, total = await hidden.list_devices()
        assert [item.name for item in items] == ["生物显微镜"]
        assert total == 1
        with pytest.raises(ApiError) as error:
            await hidden.preflight(plan)
        assert error.value.code == "DEVICE_NOT_FOUND"

    async with factory() as session:
        conflict = ReservationService(session, principal(student1, "STUDENT"))
        with pytest.raises(ApiError) as error:
            await conflict.create(
                ReservationPlanRequest(
                    device_id=device.id,
                    start_date=target,
                    end_date=target,
                    purpose="重复预约",
                )
            )
        assert error.value.code == "RESERVATION_CONFLICT"

    async with factory() as session:
        cancelled = await ReservationService(session, principal(student1, "STUDENT")).cancel(
            first.created[0].id
        )
        assert cancelled.status == "CANCELLED"
        reopened = await ReservationService(session, principal(student1, "STUDENT")).create(
            ReservationPlanRequest(
                device_id=device.id,
                start_date=target,
                end_date=target,
                purpose="释放后重新预约",
            )
        )
        assert reopened.created[0].status == "APPROVED"


@pytest.mark.asyncio
async def test_adjacent_explicit_dates_create_independent_reservations(seeded) -> None:
    factory, _, _, student, _, _, device, _ = seeded
    first_date = date.today() + timedelta(days=4)
    second_date = first_date + timedelta(days=1)
    async with factory() as session:
        result = await ReservationService(
            session,
            principal(student, "STUDENT"),
        ).create(
            ReservationPlanRequest(
                device_id=device.id,
                dates=[first_date, second_date],
                purpose="相邻日期按独立预约办理交接",
            )
        )
        assert len(result.created) == 2
        assert [item.dates for item in result.created] == [[first_date], [second_date]]
        rows = list(
            (
                await session.scalars(
                    select(Reservation)
                    .where(Reservation.id.in_([item.id for item in result.created]))
                    .order_by(Reservation.start_date)
                )
            ).all()
        )
        assert len(rows) == 2
        assert all(row.start_date == row.end_date for row in rows)
        assert rows[0].batch_id is not None
        assert rows[0].batch_id == rows[1].batch_id == result.batch_id


@pytest.mark.asyncio
async def test_available_only_does_not_split_continuous_range_on_conflict(seeded) -> None:
    factory, _, _, student, _, _, device, _ = seeded
    first_date = date.today() + timedelta(days=5)
    conflict_date = first_date + timedelta(days=1)
    last_date = first_date + timedelta(days=2)
    async with factory() as session:
        service = ReservationService(session, principal(student, "STUDENT"))
        await service.create(
            ReservationPlanRequest(
                device_id=device.id,
                start_date=conflict_date,
                end_date=conflict_date,
                purpose="制造连续区间中的冲突日期",
            )
        )
        before_count = await session.scalar(select(func.count(Reservation.id)))
        with pytest.raises(ApiError) as error:
            await service.create(
                ReservationPlanRequest(
                    device_id=device.id,
                    start_date=first_date,
                    end_date=last_date,
                    commit_mode="available_only",
                    purpose="连续区间不可跳过冲突日拆单",
                )
            )
        after_count = await session.scalar(select(func.count(Reservation.id)))

    assert error.value.code == "RESERVATION_CONFLICT"
    assert before_count == after_count


@pytest.mark.asyncio
async def test_conflict_with_suggestions_returns_domain_error(seeded) -> None:
    factory, college, _, student, _, _, device, _ = seeded
    target = date.today() + timedelta(days=2)
    async with factory() as session:
        category = DeviceCategory(name="冲突推荐测试分类", parent_id=0, sort=0)
        session.add(category)
        await session.flush()
        device.category_id = category.id
        alternative = Device(
            name="同类空闲设备",
            college_id=college.id,
            lab_id=device.lab_id,
            category_id=category.id,
            status="IDLE",
            need_approval=False,
            max_reservation_days=8,
        )
        session.add_all([device, alternative])
        await session.commit()

        service = ReservationService(session, principal(student, "STUDENT"))
        plan = ReservationPlanRequest(
            device_id=device.id,
            start_date=target,
            end_date=target,
            purpose="冲突推荐回归测试",
        )
        created = await service.create(plan)
        assert len(created.created) == 1

        preflight = await service.preflight(plan)
        assert preflight.all_available is False
        assert any(
            item.device_id == alternative.id for item in preflight.similar_device_suggestions
        )

        with pytest.raises(ApiError) as error:
            await service.create(plan)
        assert error.value.code == "RESERVATION_CONFLICT"


@pytest.mark.asyncio
async def test_recommendations_follow_college_and_manager_scope(seeded) -> None:
    factory, _, _, student1, student2, manager, device, other_device = seeded
    async with factory() as session:
        student_items = await RecommendationService(
            session,
            principal(student1, "STUDENT"),
        ).recommend()
        other_student_items = await RecommendationService(
            session,
            principal(student2, "STUDENT"),
        ).recommend()
        manager_items = await RecommendationService(
            session,
            principal(manager, "LAB_ADMIN"),
        ).recommend()

    assert [item.device_id for item in student_items] == [device.id]
    assert [item.device_id for item in other_student_items] == [other_device.id]
    assert [item.device_id for item in manager_items] == [device.id]


@pytest.mark.asyncio
async def test_manager_approval_is_limited_to_owned_lab(seeded) -> None:
    factory, _, _, student1, _, manager, device, _ = seeded
    device.need_approval = True
    target = date.today() + timedelta(days=4)
    async with factory() as session:
        session.add(device)
        await session.commit()
        created = await ReservationService(
            session,
            principal(student1, "STUDENT"),
        ).create(
            ReservationPlanRequest(
                device_id=device.id,
                start_date=target,
                end_date=target,
                purpose="需要审批的实验",
            )
        )
        assert created.created[0].status == "PENDING"

    async with factory() as session:
        approved = await ReservationService(
            session,
            principal(manager, "LAB_ADMIN"),
        ).approve(created.created[0].id, True)
        assert approved.status == "APPROVED"
        pending = await ReservationService(
            session,
            principal(manager, "LAB_ADMIN"),
        ).pending_approvals()
        assert pending.total == 0

        approval_notification = await session.scalar(
            select(OutboxTask).where(
                OutboxTask.task_key == f"notification:reservation:{created.created[0].id}:approved"
            )
        )
        assert approval_notification is not None
        assert approval_notification.payload["title"] == "预约申请已通过"


@pytest.mark.asyncio
async def test_non_loan_device_requires_manager_handover_and_return_acceptance(seeded) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    device.allow_external_loan = False
    day = date.today()
    async with factory() as session:
        session.add(device)
        await session.commit()
        created = await ReservationService(session, principal(student, "STUDENT")).create(
            ReservationPlanRequest(
                device_id=device.id,
                start_date=day,
                end_date=day,
                purpose="普通设备预约也需要交接",
            )
        )
        reservation_id = created.created[0].id
        assert created.created[0].status == "APPROVED"
        assert created.created[0].requires_handover is True
        assert created.created[0].handover_status == "PENDING"
        handover = await session.scalar(
            select(DeviceHandover).where(DeviceHandover.reservation_id == reservation_id)
        )
        assert handover is not None
        assert handover.status == "PENDING"

    async with factory() as session:
        student_service = ReservationService(session, principal(student, "STUDENT"))
        with pytest.raises(ApiError) as error:
            await student_service.check_in(reservation_id)
        assert error.value.code == "HANDOVER_REQUIRED"

    async with factory() as session:
        manager_service = ReservationService(session, principal(manager, "LAB_ADMIN"))
        pending = await manager_service.pending_handovers(status="PENDING")
        assert pending.total == 1
        handover_image = await add_evidence(
            session,
            manager,
            "manager-handover-evidence-00000001",
        )
        handed_over = await manager_service.handover(
            reservation_id,
            image_urls=[handover_image],
        )
        assert handed_over.status == "IN_USE"
        assert handed_over.handover_status == "HANDED_OVER"
        handover_cache_bump = await session.scalar(
            select(OutboxTask).where(
                OutboxTask.task_type == "CACHE_BUMP",
                OutboxTask.college_id == student.college_id,
            )
        )
        assert handover_cache_bump is not None

    async with factory() as session:
        return_image = await add_evidence(
            session,
            student,
            "student-return-evidence-0000000001",
        )
        returned = await ReservationService(
            session,
            principal(student, "STUDENT"),
        ).return_device(reservation_id, image_urls=[return_image])
        assert returned.status == "IN_USE"
        assert returned.handover_status == "RETURN_PENDING"

        with pytest.raises(ApiError) as error:
            await ReservationService(session, principal(student, "STUDENT")).return_device(
                reservation_id,
                image_urls=[return_image],
            )
        assert error.value.code == "INVALID_RESERVATION_STATE"

    async with factory() as session:
        manager_service = ReservationService(session, principal(manager, "LAB_ADMIN"))
        awaiting_acceptance = await manager_service.pending_handovers(status="RETURN_PENDING")
        assert awaiting_acceptance.total == 1
        mine = await ReservationService(session, principal(student, "STUDENT")).list_mine(
            handover_status="RETURN_PENDING"
        )
        assert [item.id for item in mine.items] == [reservation_id]
        session.add(
            RepairReport(
                college_id=student.college_id,
                device_id=device.id,
                reporter_id=student.id,
                title="等待报修人确认的关联工单",
                description="设备仍需保持维护状态",
                status="RESOLVED",
                priority="NORMAL",
            )
        )
        await session.commit()
        completed = await manager_service.accept_return(reservation_id)
        assert completed.status == "COMPLETED"
        assert completed.handover_status == "RETURNED"
        assert completed.dates == [day]
        current_device = await session.get(type(device), device.id)
        assert current_device is not None and current_device.status == "MAINTENANCE"
        cache_bump_count = await session.scalar(
            select(func.count(OutboxTask.id)).where(
                OutboxTask.task_type == "CACHE_BUMP",
                OutboxTask.college_id == student.college_id,
            )
        )
        assert cache_bump_count == 2


@pytest.mark.asyncio
async def test_qualification_must_cover_every_requested_natural_day(seeded) -> None:
    factory, college, _, student, _, manager, device, _ = seeded
    end_date = date.today() + timedelta(days=5)
    device.requires_qualification = True
    async with factory() as session:
        session.add(device)
        session.add(
            DeviceQualification(
                device_id=device.id,
                user_id=student.id,
                college_id=college.id,
                status="APPROVED",
                qualification_type="TRAINING",
                valid_until=end_date - timedelta(days=1),
                reviewed_by=manager.id,
            )
        )
        await session.commit()
        result = await ReservationService(
            session,
            principal(student, "STUDENT"),
        ).preflight(
            ReservationPlanRequest(
                device_id=device.id,
                start_date=end_date - timedelta(days=2),
                end_date=end_date,
                purpose="多日培训实验",
            )
        )
        assert result.qualification_required is True
        assert result.qualification_approved is False
        assert result.qualification_valid_until == end_date - timedelta(days=1)


@pytest.mark.asyncio
async def test_abnormal_handover_creates_repair_and_keeps_booking_unstarted(seeded) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    day = date.today()
    async with factory() as session:
        created = await ReservationService(session, principal(student, "STUDENT")).create(
            ReservationPlanRequest(
                device_id=device.id,
                start_date=day,
                end_date=day,
                purpose="交接异常维修验证",
            )
        )
        reservation_id = created.created[0].id
        image = await add_evidence(session, manager, "manager-exception-evidence-0000001")
        result = await ReservationService(session, principal(manager, "LAB_ADMIN")).handover(
            reservation_id,
            condition="DAMAGED",
            note="机身外壳破损",
            image_urls=[image],
        )
        assert result.status == "APPROVED"
        assert result.handover_status == "EXCEPTION"
        assert result.fault_repair_id is not None
        repair = await session.scalar(
            select(RepairReport).where(RepairReport.reservation_id == reservation_id)
        )
        assert repair is not None
        assert repair.status == "PENDING"
        assert repair.image_urls == [image]

    async with factory() as session:
        with pytest.raises(ApiError) as error:
            await ReservationService(session, principal(student, "STUDENT")).check_in(
                reservation_id
            )
        assert error.value.code == "HANDOVER_REQUIRED"


@pytest.mark.asyncio
async def test_handover_compare_and_set_rejects_stale_normal_and_exception_actions(
    seeded,
    monkeypatch,
) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    today = date.today()

    async def make_approved_reservation(target_device):
        async with factory() as session:
            created = await ReservationService(
                session,
                principal(student, "STUDENT"),
            ).create(
                ReservationPlanRequest(
                    device_id=target_device.id,
                    start_date=today,
                    end_date=today,
                    purpose="交接状态并发条件更新验证",
                )
            )
            return created.created[0].id

    # A stale abnormal-handover request must not overwrite an already completed
    # normal handover or create a repair ticket.
    reservation_id = await make_approved_reservation(device)
    async with factory() as session:
        service = ReservationService(session, principal(manager, "LAB_ADMIN"))
        stale = await service._load_reservation(reservation_id)
        await session.execute(
            update(Reservation)
            .where(Reservation.id == reservation_id)
            .values(status="IN_USE", handover_status="HANDED_OVER")
            .execution_options(synchronize_session=False)
        )
        image = await add_evidence(session, manager, "stale-exception-handover-0001")
        await session.commit()

        async def load_stale(_reservation_id: int):
            return stale

        monkeypatch.setattr(service, "_load_reservation", load_stale)
        with pytest.raises(ApiError) as error:
            await service.handover(
                reservation_id,
                condition="DAMAGED",
                image_urls=[image],
            )
        assert error.value.code == "RESERVATION_STATE_CHANGED"
        await session.rollback()

    async with factory() as session:
        persisted = await session.get(Reservation, reservation_id)
        handover = await session.scalar(
            select(DeviceHandover).where(DeviceHandover.reservation_id == reservation_id)
        )
        repair = await session.scalar(
            select(RepairReport).where(RepairReport.reservation_id == reservation_id)
        )
        assert persisted is not None and persisted.status == "IN_USE"
        assert persisted.handover_status == "HANDED_OVER"
        assert handover is not None and handover.status == "PENDING"
        assert repair is None
        await session.execute(
            delete(ReservationItem).where(ReservationItem.reservation_id == reservation_id)
        )
        await session.commit()

    # A stale normal-handover request must not erase an exception recorded by
    # the competing transaction.
    reservation_id = await make_approved_reservation(device)
    async with factory() as session:
        service = ReservationService(session, principal(manager, "LAB_ADMIN"))
        stale = await service._load_reservation(reservation_id)
        await session.execute(
            update(Reservation)
            .where(Reservation.id == reservation_id)
            .values(status="APPROVED", handover_status="EXCEPTION")
            .execution_options(synchronize_session=False)
        )
        image = await add_evidence(session, manager, "stale-normal-handover-00001")
        await session.commit()

        async def load_stale(_reservation_id: int):
            return stale

        monkeypatch.setattr(service, "_load_reservation", load_stale)
        with pytest.raises(ApiError) as error:
            await service.handover(reservation_id, image_urls=[image])
        assert error.value.code == "RESERVATION_STATE_CHANGED"
        await session.rollback()

    async with factory() as session:
        persisted = await session.get(Reservation, reservation_id)
        handover = await session.scalar(
            select(DeviceHandover).where(DeviceHandover.reservation_id == reservation_id)
        )
        assert persisted is not None and persisted.status == "APPROVED"
        assert persisted.handover_status == "EXCEPTION"
        assert handover is not None and handover.status == "PENDING"


@pytest.mark.asyncio
async def test_system_admin_can_attach_tenant_neutral_upload_to_college_handover(seeded) -> None:
    factory, _, _, student, _, _, device, _ = seeded
    day = date.today()
    async with factory() as session:
        sys_admin_role = await session.scalar(
            select(Role).where(Role.role_code == "SYS_ADMIN")
        )
        assert sys_admin_role is not None
        admin = User(
            username="global-admin",
            password_hash="test",
            real_name="系统管理员",
            college_id=None,
            status=1,
            roles=[sys_admin_role],
        )
        session.add(admin)
        await session.flush()
        created = await ReservationService(session, principal(student, "STUDENT")).create(
            ReservationPlanRequest(
                device_id=device.id,
                start_date=day,
                end_date=day,
                purpose="系统管理员跨学院交接验证",
            )
        )
        reservation_id = created.created[0].id
        image = await add_evidence(session, admin, "global-admin-evidence-0000000001")
        result = await ReservationService(session, principal(admin, "SYS_ADMIN")).handover(
            reservation_id,
            image_urls=[image],
        )
        assert result.status == "IN_USE"
        assert result.handover_status == "HANDED_OVER"


@pytest.mark.asyncio
async def test_handover_cannot_restore_a_device_with_an_open_repair(seeded) -> None:
    factory, college, _, student, _, manager, device, _ = seeded
    day = date.today()
    async with factory() as session:
        created = await ReservationService(session, principal(student, "STUDENT")).create(
            ReservationPlanRequest(
                device_id=device.id,
                start_date=day,
                end_date=day,
                purpose="维修中设备不得交接",
            )
        )
        reservation_id = created.created[0].id
        reservation = await session.get(Reservation, reservation_id)
        assert reservation is not None
        reservation.status = "APPROVED"
        reservation.handover_status = "PENDING"
        current_device = await session.get(Device, device.id)
        assert current_device is not None
        current_device.status = "MAINTENANCE"
        await session.commit()

    async with factory() as session:
        with pytest.raises(ApiError) as unavailable:
            await ReservationService(session, principal(manager, "LAB_ADMIN")).handover(
                reservation_id
            )
        assert unavailable.value.code == "DEVICE_UNAVAILABLE"

    async with factory() as session:
        current_device = await session.get(Device, device.id)
        assert current_device is not None
        current_device.status = "IDLE"
        session.add(
            RepairReport(
                college_id=college.id,
                device_id=device.id,
                reporter_id=student.id,
                title="交接前设备故障",
                status="PENDING",
                priority="NORMAL",
            )
        )
        await session.commit()

    async with factory() as session:
        with pytest.raises(ApiError) as open_repair:
            await ReservationService(session, principal(manager, "LAB_ADMIN")).handover(
                reservation_id
            )
        assert open_repair.value.code == "DEVICE_REPAIR_OPEN"
