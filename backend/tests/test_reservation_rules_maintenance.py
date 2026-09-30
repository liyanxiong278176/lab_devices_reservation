from datetime import date, timedelta
from unittest.mock import AsyncMock

import app.application.maintenance as maintenance_module
import pytest
from app.api.v2.maintenance import list_maintenance_devices
from app.api.v2.reservation_rules import list_reservation_rules
from app.api.v2.schemas import MaintenancePlanWrite, MaintenanceRecordCreate, ReservationPlanRequest
from app.application.maintenance import MaintenanceService, add_interval, utcnow_naive
from app.application.repairs import RepairService
from app.application.reservations import ReservationService
from app.application.scope_access import can_manage_scope
from app.auth.security import Principal
from app.core.errors import ApiError
from app.core.settings import Settings
from app.infrastructure.db.models import (
    Device,
    DeviceMaintenancePlan,
    DeviceMaintenanceRecord,
    Lab,
    OutboxTask,
    RepairReport,
    RepairWorklog,
    Reservation,
    ReservationBlackout,
    ReservationRule,
    ReservationWaitlist,
    ReservationWaitlistOffer,
    Role,
    UploadAsset,
    User,
)
from app.infrastructure.tasks.worker import OutboxWorker
from fastapi import FastAPI
from sqlalchemy import event, func, select


def principal(user, *roles: str) -> Principal:
    permission_map = {
        "STUDENT": (
            "dashboard:read", "device:read", "reservation:create", "reservation:read:own",
            "reservation:cancel", "reservation:check-in", "reservation:return",
            "repair:create", "repair:read:own", "repair:confirm", "feedback:create",
        ),
        "LAB_ADMIN": (
            "dashboard:read", "device:read", "device:manage", "device:documents:manage",
            "reservation:read:scope", "reservation:approve", "reservation:handover",
            "reservation:accept-return", "repair:read:scope", "repair:handle",
            "reservation:create", "repair:confirm",
            "report:read", "reservation-rule:manage", "maintenance:manage",
            "feedback:read:scope", "organization:read",
        ),
    }
    return Principal(
        user_id=user.id,
        username=user.username,
        college_id=user.college_id,
        roles=roles,
        token_type="access",
        token_id="rules-maintenance-test",
        permissions=tuple({code for role in roles for code in permission_map.get(role, ())}),
    )


@pytest.mark.asyncio
async def test_device_catalog_search_matches_asset_code(seeded) -> None:
    factory, _, _, student, _, _, device, _ = seeded
    async with factory() as session:
        stored_device = await session.get(Device, device.id)
        assert stored_device is not None
        stored_device.asset_code = "CSE-DEVICE-042"
        await session.commit()

        items, total = await ReservationService(
            session, principal(student, "STUDENT")
        ).list_devices(search="CSE-DEVICE-042")

    assert total == 1
    assert [item.id for item in items] == [device.id]


@pytest.mark.asyncio
async def test_rule_and_maintenance_mutations_require_existing_managed_scope(seeded) -> None:
    factory, _, _, student, _, manager, device, other_device = seeded
    async with factory() as session:
        manager_principal = principal(manager, "LAB_ADMIN")
        assert await can_manage_scope(session, manager_principal, "DEVICE", device.id)
        assert not await can_manage_scope(session, manager_principal, "DEVICE", other_device.id)
        assert not await can_manage_scope(session, manager_principal, "GLOBAL", 0)
        assert not await can_manage_scope(
            session,
            principal(manager, "SYS_ADMIN"),
            "DEVICE",
            999_999,
        )
        assert not await can_manage_scope(
            session,
            principal(student, "STUDENT"),
            "DEVICE",
            device.id,
        )

        with pytest.raises(ApiError) as error:
            await MaintenanceService(session, manager_principal).create_plan(
                other_device.id,
                MaintenancePlanWrite(
                    plan_type="ROUTINE",
                    title="unauthorized maintenance plan",
                    interval_value=1,
                    interval_unit="YEAR",
                    due_date=date.today() + timedelta(days=30),
                ),
            )
        assert error.value.code == "DEVICE_NOT_FOUND"


@pytest.mark.asyncio
async def test_identity_policy_cannot_be_relaxed_by_generic_device_rule(seeded) -> None:
    factory, college, _, student, _, _, device, _ = seeded
    async with factory() as session:
        session.add_all(
            [
                ReservationRule(
                    scope_type="COLLEGE",
                    scope_id=college.id,
                    user_category="STUDENT",
                    max_booking_days=2,
                    max_advance_days=10,
                    approval_required=True,
                ),
                ReservationRule(
                    scope_type="DEVICE",
                    scope_id=device.id,
                    user_category="ALL",
                    max_booking_days=4,
                    max_advance_days=30,
                    approval_required=False,
                ),
            ]
        )
        await session.commit()
        service = ReservationService(session, principal(student, "STUDENT"))
        preflight = await service.preflight(
            ReservationPlanRequest(
                device_id=device.id,
                start_date=date.today() + timedelta(days=2),
                end_date=date.today() + timedelta(days=2),
                purpose="规则审批验证",
            )
        )
        assert preflight.effective_policy.max_booking_days == 2
        assert preflight.effective_policy.max_advance_days == 10
        assert preflight.effective_policy.approval_required is True

        disjoint_preflight = await service.preflight(
            ReservationPlanRequest(
                device_id=device.id,
                dates=[
                    date.today() + timedelta(days=4),
                    date.today() + timedelta(days=6),
                    date.today() + timedelta(days=8),
                ],
                purpose="互不连续日期应分别按单次预约校验",
            )
        )
        assert len(disjoint_preflight.available_dates) == 3

        with pytest.raises(ApiError) as error:
            await service.preflight(
                ReservationPlanRequest(
                    device_id=device.id,
                    start_date=date.today() + timedelta(days=4),
                    end_date=date.today() + timedelta(days=6),
                    purpose="连续预约身份规则不得被通用设备规则放宽",
                )
            )
        assert error.value.code == "DATE_RANGE_TOO_LARGE"


@pytest.mark.asyncio
async def test_generic_advance_rule_preserves_role_defaults(seeded) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    async with factory() as session:
        session.add(
            ReservationRule(
                scope_type="DEVICE",
                scope_id=device.id,
                user_category="ALL",
                max_advance_days=120,
            )
        )
        await session.commit()

        student_service = ReservationService(session, principal(student, "STUDENT"))
        student_policy = await student_service.preflight(
            ReservationPlanRequest(
                device_id=device.id,
                start_date=date.today() + timedelta(days=30),
                end_date=date.today() + timedelta(days=30),
                purpose="普通用户默认提前期验证",
            )
        )
        assert student_policy.effective_policy.max_advance_days == 30
        with pytest.raises(ApiError) as student_error:
            await student_service.preflight(
                ReservationPlanRequest(
                    device_id=device.id,
                    start_date=date.today() + timedelta(days=31),
                    end_date=date.today() + timedelta(days=31),
                    purpose="通用规则不能放宽普通用户默认提前期",
                )
            )
        assert student_error.value.code == "DATE_TOO_FAR"

        manager_service = ReservationService(session, principal(manager, "LAB_ADMIN"))
        manager_policy = await manager_service.preflight(
            ReservationPlanRequest(
                device_id=device.id,
                start_date=date.today() + timedelta(days=90),
                end_date=date.today() + timedelta(days=90),
                purpose="负责人默认提前期验证",
            )
        )
        assert manager_policy.effective_policy.max_advance_days == 90
        with pytest.raises(ApiError) as manager_error:
            await manager_service.preflight(
                ReservationPlanRequest(
                    device_id=device.id,
                    start_date=date.today() + timedelta(days=91),
                    end_date=date.today() + timedelta(days=91),
                    purpose="通用规则不能放宽负责人默认提前期",
                )
            )
        assert manager_error.value.code == "DATE_TOO_FAR"

        identity_rule = ReservationRule(
            scope_type="DEVICE",
            scope_id=device.id,
            user_category="STUDENT",
            max_advance_days=40,
        )
        session.add(identity_rule)
        await session.commit()
        extended_student_policy = await student_service.preflight(
            ReservationPlanRequest(
                device_id=device.id,
                start_date=date.today() + timedelta(days=40),
                end_date=date.today() + timedelta(days=40),
                purpose="身份专属规则可覆盖默认提前期",
            )
        )
        assert extended_student_policy.effective_policy.max_advance_days == 40


@pytest.mark.asyncio
async def test_system_admin_is_subject_to_configured_advance_horizon(seeded) -> None:
    factory, _, _, _, _, admin, device, _ = seeded
    async with factory() as session:
        service = ReservationService(session, principal(admin, "SYS_ADMIN"))
        with pytest.raises(ApiError) as error:
            await service.preflight(
                ReservationPlanRequest(
                    device_id=device.id,
                    start_date=date.today() + timedelta(days=91),
                    end_date=date.today() + timedelta(days=91),
                    purpose="管理员预约同样遵守配置的提前期",
                )
            )
        assert error.value.code == "DATE_TOO_FAR"


@pytest.mark.asyncio
async def test_reservation_rule_list_uses_bounded_page_number_pagination(seeded) -> None:
    factory, _, _, _, _, admin, _, _ = seeded
    async with factory() as session:
        session.add_all(
            [
                ReservationRule(
                    scope_type="DEVICE",
                    scope_id=50_000 + index,
                    user_category="ALL",
                    max_booking_days=1,
                )
                for index in range(25)
            ]
        )
        await session.commit()

        first = await list_reservation_rules(
            page=1,
            page_size=10,
            scope_type=None,
            user_category=None,
            scope_id=None,
            principal=principal(admin, "SYS_ADMIN"),
            session=session,
        )
        second = await list_reservation_rules(
            page=2,
            page_size=10,
            scope_type=None,
            user_category=None,
            scope_id=None,
            principal=principal(admin, "SYS_ADMIN"),
            session=session,
        )
        filtered = await list_reservation_rules(
            page=1,
            page_size=10,
            scope_type="DEVICE",
            user_category="ALL",
            scope_id=50_007,
            principal=principal(admin, "SYS_ADMIN"),
            session=session,
        )

        assert first.data is not None and second.data is not None and filtered.data is not None
        assert first.data.total == 25
        assert first.data.page == 1 and first.data.pages == 3
        assert len(first.data.items) == 10
        assert len(second.data.items) == 10
        assert first.data.items[0].id > second.data.items[0].id
        assert filtered.data.total == 1 and filtered.data.items[0].scope_id == 50_007
        with pytest.raises(ApiError) as error:
            await list_reservation_rules(
                page=5_002,
                page_size=20,
                principal=principal(admin, "SYS_ADMIN"),
                session=session,
            )
        assert error.value.code == "PAGE_DEPTH_EXCEEDED"


@pytest.mark.asyncio
async def test_maintenance_rechecks_manager_scope_after_device_lock(seeded, monkeypatch) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    async with factory() as session:
        original = ReservationService._can_manage_device
        checks = 0

        async def transfer_after_first_check(service, current_device):
            nonlocal checks
            checks += 1
            allowed = await original(service, current_device)
            if checks == 1:
                lab = await session.get(Lab, device.lab_id)
                assert lab is not None
                lab.manager_id = student.id
                await session.flush()
            return allowed

        monkeypatch.setattr(ReservationService, "_can_manage_device", transfer_after_first_check)
        with pytest.raises(ApiError) as error:
            await MaintenanceService(session, principal(manager, "LAB_ADMIN"))._managed_device(
                device.id,
                lock=True,
            )
        assert checks == 2
        assert error.value.code == "FORBIDDEN"


@pytest.mark.asyncio
async def test_reservation_count_and_total_device_days_are_not_capped(seeded) -> None:
    factory, college, _, student, _, _, device, _ = seeded
    async with factory() as session:
        second_device = Device(
            name="第二台工作站",
            college_id=college.id,
            lab_id=device.lab_id,
            status="IDLE",
            need_approval=False,
            max_reservation_days=1,
        )
        device.max_reservation_days = 1
        session.add_all([device, second_device])
        await session.commit()

    created_ids: list[int] = []
    async with factory() as session:
        service = ReservationService(session, principal(student, "STUDENT"))
        for offset in range(1, 17):
            for device_id in (device.id, second_device.id):
                target = date.today() + timedelta(days=offset)
                result = await service.create(
                    ReservationPlanRequest(
                        device_id=device_id,
                        start_date=target,
                        end_date=target,
                        purpose="预约额度移除回归验证",
                    )
                )
                created_ids.extend(row.id for row in result.created)
        assert len(created_ids) == 32

    async with factory() as session:
        total = await session.scalar(
            select(func.count(Reservation.id)).where(Reservation.user_id == student.id)
        )
        assert total == 32


@pytest.mark.asyncio
async def test_calibration_is_not_blocked_before_due_but_is_blocked_after_due(seeded) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    future_day = date.today() + timedelta(days=3)
    async with factory() as session:
        plan = await MaintenanceService(session, principal(manager, "LAB_ADMIN")).create_plan(
            device.id,
            MaintenancePlanWrite(
                plan_type="CALIBRATION",
                title="年度校准",
                interval_value=12,
                interval_unit="MONTH",
                due_date=date.today() + timedelta(days=1),
            ),
        )
        service = ReservationService(session, principal(student, "STUDENT"))
        before_due = await service.preflight(
            ReservationPlanRequest(
                device_id=device.id,
                start_date=future_day,
                end_date=future_day,
                purpose="校准到期前预约",
            )
        )
        assert before_due.all_available is True

        current_plan = await session.get(DeviceMaintenancePlan, plan.id)
        assert current_plan is not None
        current_plan.due_date = date.today() - timedelta(days=1)
        await session.commit()

        after_due = await service.preflight(
            ReservationPlanRequest(
                device_id=device.id,
                start_date=future_day,
                end_date=future_day,
                purpose="校准逾期后预约",
            )
        )
        assert after_due.all_available is False
        assert "已逾期" in after_due.conflicts[0].reason
        current_device = await session.get(Device, device.id)
        assert current_device is not None and current_device.status == "IDLE"


@pytest.mark.asyncio
async def test_custom_blackout_reason_is_not_misclassified_as_maintenance(seeded) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    target = date.today() + timedelta(days=2)
    async with factory() as session:
        session.add(
            ReservationBlackout(
                scope_type="DEVICE",
                scope_id=device.id,
                blocked_date=target,
                reason="设备暂不可预约",
                active=True,
                created_by=manager.id,
            )
        )
        await session.commit()
        result = await ReservationService(
            session, principal(student, "STUDENT")
        ).availability(device.id, target, target)
        assert result[0].available is False
        assert result[0].status == "BLACKOUT"


@pytest.mark.asyncio
async def test_conflict_suggestions_respect_effective_advance_rule(seeded) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    target = date.today() + timedelta(days=3)
    async with factory() as session:
        session.add(
            ReservationRule(
                scope_type="DEVICE",
                scope_id=device.id,
                user_category="STUDENT",
                max_advance_days=5,
                created_by=manager.id,
                updated_by=manager.id,
            )
        )
        await session.commit()

        service = ReservationService(session, principal(student, "STUDENT"))
        await service.create(
            ReservationPlanRequest(
                device_id=device.id,
                start_date=target,
                end_date=target,
                purpose="创建一个占用日期供建议测试",
            )
        )
        preflight = await service.preflight(
            ReservationPlanRequest(
                device_id=device.id,
                start_date=target,
                end_date=target,
                purpose="验证冲突日期建议不超出规则提前期",
            )
        )
        assert preflight.effective_policy.max_advance_days == 5
        assert preflight.all_available is False
        assert preflight.same_device_suggestions
        assert all(
            suggestion.end_date <= date.today() + timedelta(days=5)
            for suggestion in preflight.same_device_suggestions
        )


@pytest.mark.asyncio
async def test_downtime_plan_rejects_overlapping_reservation(seeded) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    blocked_day = date.today() + timedelta(days=5)
    async with factory() as session:
        result = await ReservationService(session, principal(student, "STUDENT")).create(
            ReservationPlanRequest(
                device_id=device.id,
                start_date=blocked_day,
                end_date=blocked_day,
                purpose="维护停机冲突预约",
            )
        )
        assert result.created[0].status == "APPROVED"

    async with factory() as session:
        with pytest.raises(ApiError) as error:
            await MaintenanceService(session, principal(manager, "LAB_ADMIN")).create_plan(
                device.id,
                MaintenancePlanWrite(
                    plan_type="ROUTINE",
                    title="设备年度保养",
                    interval_value=1,
                    interval_unit="YEAR",
                    due_date=blocked_day,
                    downtime_start=blocked_day,
                    downtime_end=blocked_day,
                ),
            )
        assert error.value.code == "MAINTENANCE_DOWNTIME_CONFLICT"
        assert error.value.data["conflicts"][0]["reservation_id"] == result.created[0].id

        inactive = await MaintenanceService(session, principal(manager, "LAB_ADMIN")).create_plan(
            device.id,
            MaintenancePlanWrite(
                plan_type="ROUTINE",
                title="尚未启用的保养草案",
                interval_value=1,
                interval_unit="YEAR",
                due_date=blocked_day,
                downtime_start=blocked_day,
                downtime_end=blocked_day,
                active=False,
            ),
        )
        assert inactive.active is False


@pytest.mark.asyncio
async def test_downtime_plan_rejects_active_waitlist_hold(seeded) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    blocked_day = date.today() + timedelta(days=5)
    async with factory() as session:
        entry = ReservationWaitlist(
            device_id=device.id,
            college_id=student.college_id,
            user_id=student.id,
            reservation_date=blocked_day,
            purpose="候补保留冲突验证",
            status="OFFERED",
        )
        session.add(entry)
        await session.flush()
        session.add(
            ReservationWaitlistOffer(
                waitlist_id=entry.id,
                device_id=device.id,
                college_id=student.college_id,
                user_id=student.id,
                reservation_date=blocked_day,
                expires_at=utcnow_naive() + timedelta(hours=1),
            )
        )
        await session.commit()

        with pytest.raises(ApiError) as error:
            await MaintenanceService(session, principal(manager, "LAB_ADMIN")).create_plan(
                device.id,
                MaintenancePlanWrite(
                    plan_type="ROUTINE",
                    title="候补日期维护停机",
                    interval_value=1,
                    interval_unit="YEAR",
                    due_date=blocked_day,
                    downtime_start=blocked_day,
                    downtime_end=blocked_day,
                ),
            )
        assert error.value.code == "MAINTENANCE_DOWNTIME_CONFLICT"
        assert error.value.data["conflicts"] == [
            {
                "reservation_id": None,
                "waitlist_id": entry.id,
                "start_date": blocked_day.isoformat(),
                "end_date": blocked_day.isoformat(),
                "status": "WAITLIST_HOLD",
            }
        ]


@pytest.mark.asyncio
async def test_failed_calibration_requires_evidence_and_creates_linked_repair(seeded) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    async with factory() as session:
        service = MaintenanceService(session, principal(manager, "LAB_ADMIN"))
        plan = await service.create_plan(
            device.id,
            MaintenancePlanWrite(
                plan_type="CALIBRATION",
                title="光学平台校准",
                interval_value=1,
                interval_unit="YEAR",
                due_date=date.today(),
            ),
        )
        with pytest.raises(ApiError) as error:
            await service.complete_cycle(
                plan.id,
                MaintenanceRecordCreate(
                    cycle_due_date=date.today(),
                    completed_date=date.today(),
                    result="FAILED",
                    notes="精度误差超出允许范围",
                ),
                idempotency_key="calibration-no-proof-0001",
            )
        assert error.value.code == "MAINTENANCE_EVIDENCE_REQUIRED"

        evidence = UploadAsset(
            asset_token="calibration-proof-token-0001",
            user_id=manager.id,
            college_id=manager.college_id,
            original_name="校准证书.pdf",
            content_type="application/pdf",
            size_bytes=512,
            storage_path="memory://calibration-proof",
        )
        session.add(evidence)
        await session.flush()
        record_payload = MaintenanceRecordCreate(
            cycle_due_date=plan.due_date,
            completed_date=date.today(),
            result="FAILED",
            notes="精度误差超出允许范围",
            evidence_asset_token=evidence.asset_token,
        )
        record = await service.complete_cycle(
            plan.id,
            record_payload,
            idempotency_key="calibration-failed-cycle-0001",
        )
        assert record.repair_report_id is not None
        replay = await service.complete_cycle(
            plan.id,
            record_payload,
            idempotency_key="calibration-failed-cycle-0001",
        )
        assert replay.id == record.id

        with pytest.raises(ApiError) as duplicate:
            await service.complete_cycle(
                plan.id,
                record_payload,
                idempotency_key="calibration-failed-cycle-0002",
            )
        assert duplicate.value.code == "MAINTENANCE_REPAIR_NOT_COMPLETED"

        with pytest.raises(ApiError) as type_change:
            await service.update_plan(
                plan.id,
                MaintenancePlanWrite(
                    plan_type="ROUTINE",
                    title=plan.title,
                    interval_value=plan.interval_value,
                    interval_unit=plan.interval_unit,
                    due_date=plan.due_date,
                ),
            )
        assert type_change.value.code == "MAINTENANCE_PLAN_TYPE_IMMUTABLE"

    async with factory() as session:
        current_device = await session.get(Device, device.id)
        stored_record = await session.get(DeviceMaintenanceRecord, record.id)
        repair = await session.get(RepairReport, record.repair_report_id)
        worklog = await session.scalar(
            select(RepairWorklog).where(RepairWorklog.report_id == record.repair_report_id)
        )
        notification = await session.scalar(
            select(OutboxTask).where(
                OutboxTask.task_key == f"repair:{record.repair_report_id}:maintenance-failure"
            )
        )
        assert current_device is not None and current_device.status == "MAINTENANCE"
        assert stored_record is not None and stored_record.repair_report_id == repair.id
        assert repair is not None and repair.status == "PENDING"
        assert worklog is not None and "未通过" in worklog.content
        assert notification is not None
        assert notification.payload["title"] == "校准未通过，已创建报修工单"
        assert "校准计划“光学平台校准”未通过" in notification.payload["content"]

    # Repair completion restores the physical device, but only a successful
    # same-cycle maintenance retest may clear the failed calibration restriction.
    manager_principal = principal(manager, "LAB_ADMIN")
    async with factory() as session:
        repair_service = RepairService(session, manager_principal)
        await repair_service.take(repair.id)
        await repair_service.resolve(repair.id, "已完成精度调整并复测")
        await repair_service.confirm(repair.id, confirmed=True, note="复测通过")

    async with factory() as session:
        maintenance = MaintenanceService(session, manager_principal)
        current_device = await session.get(Device, device.id)
        assert current_device is not None and current_device.status == "IDLE"
        preflight = await ReservationService(
            session, principal(student, "STUDENT")
        ).preflight(
            ReservationPlanRequest(
                device_id=device.id,
                start_date=date.today() + timedelta(days=2),
                end_date=date.today() + timedelta(days=2),
                purpose="验证维修完成后仍受未通过校准限制",
            )
        )
        assert preflight.all_available is False
        assert any("未通过" in conflict.reason for conflict in preflight.conflicts)

        passing_evidence = UploadAsset(
            asset_token="calibration-proof-token-pass-0002",
            user_id=manager.id,
            college_id=manager.college_id,
            original_name="复测通过证书.pdf",
            content_type="application/pdf",
            size_bytes=512,
            storage_path="memory://calibration-proof-pass",
        )
        session.add(passing_evidence)
        await session.flush()
        passed_retest = await maintenance.complete_cycle(
            plan.id,
            MaintenanceRecordCreate(
                cycle_due_date=plan.due_date,
                completed_date=date.today(),
                result="PASSED",
                notes="维修后复测通过",
                evidence_asset_token=passing_evidence.asset_token,
            ),
            idempotency_key="calibration-passed-after-repair-0002",
        )
        assert passed_retest.id != record.id
        assert passed_retest.result == "PASSED"
        assert passed_retest.cycle_due_date == record.cycle_due_date
        available = await ReservationService(
            session, principal(student, "STUDENT")
        ).preflight(
            ReservationPlanRequest(
                device_id=device.id,
                start_date=date.today() + timedelta(days=2),
                end_date=date.today() + timedelta(days=2),
                purpose="验证校准通过后恢复预约",
            )
        )
        assert available.all_available is True


@pytest.mark.asyncio
async def test_passed_cycle_can_be_retried_after_due_date_advances(seeded) -> None:
    factory, _, _, _, _, manager, device, _ = seeded
    async with factory() as session:
        service = MaintenanceService(session, principal(manager, "LAB_ADMIN"))
        plan = await service.create_plan(
            device.id,
            MaintenancePlanWrite(
                plan_type="ROUTINE",
                title="定期保养幂等验证",
                interval_value=1,
                interval_unit="MONTH",
                due_date=date.today(),
            ),
        )
        payload = MaintenanceRecordCreate(
            cycle_due_date=plan.due_date,
            completed_date=date.today(),
            result="PASSED",
            notes="润滑并检查完成",
        )
        first = await service.complete_cycle(
            plan.id,
            payload,
            idempotency_key="routine-cycle-retry-0001",
        )
        retry = await service.complete_cycle(
            plan.id,
            payload,
            idempotency_key="routine-cycle-retry-0001",
        )
        assert first.id == retry.id

        with pytest.raises(ApiError) as error:
            await service.complete_cycle(
                plan.id,
                payload.model_copy(update={"notes": "不同的维护记录"}),
                idempotency_key="routine-cycle-retry-0001",
            )
        assert error.value.code == "IDEMPOTENCY_REUSED"


@pytest.mark.asyncio
async def test_plan_type_cannot_change_after_due_notification_was_sent(seeded) -> None:
    factory, _, _, _, _, manager, device, _ = seeded
    async with factory() as session:
        service = MaintenanceService(session, principal(manager, "LAB_ADMIN"))
        plan = await service.create_plan(
            device.id,
            MaintenancePlanWrite(
                plan_type="ROUTINE",
                title="已提醒的保养计划",
                interval_value=1,
                interval_unit="YEAR",
                due_date=date.today(),
            ),
        )
        stored_plan = await session.get(DeviceMaintenancePlan, plan.id)
        assert stored_plan is not None and stored_plan.updated_at is not None
        stored_plan.due_notice_sent_at = stored_plan.updated_at
        await session.commit()

        with pytest.raises(ApiError) as error:
            await service.update_plan(
                plan.id,
                MaintenancePlanWrite(
                    plan_type="CALIBRATION",
                    title=plan.title,
                    interval_value=plan.interval_value,
                    interval_unit=plan.interval_unit,
                    due_date=plan.due_date,
                ),
            )
        assert error.value.code == "MAINTENANCE_PLAN_TYPE_IMMUTABLE"


@pytest.mark.asyncio
async def test_maintenance_plan_list_default_includes_inactive_plans(seeded) -> None:
    factory, _, _, _, _, manager, device, _ = seeded
    async with factory() as session:
        service = MaintenanceService(session, principal(manager, "LAB_ADMIN"))
        active = await service.create_plan(
            device.id,
            MaintenancePlanWrite(
                plan_type="ROUTINE",
                title="启用中的计划",
                interval_value=1,
                interval_unit="YEAR",
                due_date=date.today() + timedelta(days=30),
                active=True,
            ),
        )
        inactive = await service.create_plan(
            device.id,
            MaintenancePlanWrite(
                plan_type="ROUTINE",
                title="停用的计划",
                interval_value=1,
                interval_unit="YEAR",
                due_date=date.today() + timedelta(days=60),
                active=False,
            ),
        )
        all_plans = await service.list_plans()
        active_only = await service.list_plans(active=True)
        inactive_only = await service.list_plans(active=False)
        assert {row.id for row in all_plans.items} >= {active.id, inactive.id}
        assert all(row.active for row in active_only.items)
        assert all(not row.active for row in inactive_only.items)


@pytest.mark.asyncio
async def test_maintenance_device_selector_excludes_soft_deleted_devices(seeded) -> None:
    factory, college, _, _, _, manager, device, _ = seeded
    async with factory() as session:
        deleted = Device(
            name="已删除的实验设备",
            college_id=college.id,
            lab_id=device.lab_id,
            status="DELETED",
            need_approval=False,
        )
        session.add(deleted)
        await session.commit()
        deleted_id = deleted.id

        response = await list_maintenance_devices(
            page=1,
            page_size=100,
            search=None,
            principal=principal(manager, "LAB_ADMIN"),
            session=session,
        )
        rows = response.data["items"]
        ids = {row.id for row in rows}
        assert device.id in ids
        assert deleted_id not in ids


@pytest.mark.asyncio
async def test_batch_approval_loads_maintenance_restrictions_in_batches(seeded) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    async with factory() as session:
        current_device = await session.get(Device, device.id)
        assert current_device is not None
        current_device.need_approval = True
        await session.commit()

    reservation_ids: list[int] = []
    async with factory() as session:
        service = ReservationService(session, principal(student, "STUDENT"))
        for offset in range(1, 9):
            requested_date = date.today() + timedelta(days=offset)
            result = await service.create(
                ReservationPlanRequest(
                    device_id=device.id,
                    start_date=requested_date,
                    end_date=requested_date,
                    purpose=f"批量审批查询数验证 {offset}",
                )
            )
            reservation_ids.extend(row.id for row in result.created)

    engine = factory.kw["bind"].sync_engine
    statements: list[str] = []

    def record_statement(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.lower())

    event.listen(engine, "before_cursor_execute", record_statement)
    try:
        async with factory() as session:
            approved = await ReservationService(
                session, principal(manager, "LAB_ADMIN")
            ).approve_many(reservation_ids)
            assert approved == len(reservation_ids)
    finally:
        event.remove(engine, "before_cursor_execute", record_statement)

    blackout_queries = [sql for sql in statements if "v2_reservation_blackout" in sql]
    maintenance_queries = [sql for sql in statements if "v2_device_maintenance_plan" in sql]
    assert len(blackout_queries) == 1
    # One batched availability lookup plus one batched due-notification lookup.
    assert len(maintenance_queries) == 2


def test_month_and_year_interval_rollovers_clip_to_month_end() -> None:
    assert add_interval(date(2026, 1, 31), 1, "MONTH") == date(2026, 2, 28)
    assert add_interval(date(2024, 2, 29), 1, "YEAR") == date(2025, 2, 28)


@pytest.mark.asyncio
async def test_due_outbox_notifies_manager_and_impacted_user_once(seeded) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    due_date = date.today()
    reservation_date = due_date + timedelta(days=2)
    async with factory() as session:
        current_device = await session.get(Device, device.id)
        assert current_device is not None
        current_device.need_approval = True
        await session.commit()
        reservation = await ReservationService(session, principal(student, "STUDENT")).create(
            ReservationPlanRequest(
                device_id=device.id,
                start_date=reservation_date,
                end_date=reservation_date,
                purpose="校准周期前已批准的预约",
            )
        )
        assert reservation.created[0].status == "PENDING"
        plan = DeviceMaintenancePlan(
            device_id=device.id,
            college_id=device.college_id,
            plan_type="CALIBRATION",
            title="年度校准",
            interval_value=1,
            interval_unit="YEAR",
            due_date=due_date,
            active=True,
            created_by=manager.id,
            updated_by=manager.id,
        )
        session.add(plan)
        await session.commit()
        plan_id = plan.id

    app = FastAPI()
    app.state.settings = Settings(environment="test", cors_origins=[], enable_workers=False)
    app.state.session_factory = factory
    worker = OutboxWorker(app)
    payload = {"plan_id": plan_id, "due_date": due_date.isoformat()}
    await worker._handle("MAINTENANCE_DUE", payload, task_key="maintenance-due-test-0001")
    await worker._handle("MAINTENANCE_DUE", payload, task_key="maintenance-due-test-0002")
    async with factory() as session:
        await ReservationService(
            session,
            principal(manager, "LAB_ADMIN"),
        ).approve(reservation.created[0].id, approve=True)
    async with factory() as session:
        plan = await session.get(DeviceMaintenancePlan, plan_id)
        assert plan is not None
        plan.due_date = due_date + timedelta(days=1)
        plan.due_notice_sent_at = None
        await session.commit()
        plan.due_date = due_date
        plan.due_notice_sent_at = None
        await session.commit()
    await worker._handle("MAINTENANCE_DUE", payload, task_key="maintenance-due-test-0003")

    async with factory() as session:
        plan = await session.get(DeviceMaintenancePlan, plan_id)
        notifications = list(
            (
                await session.scalars(
                    select(OutboxTask).where(
                        OutboxTask.task_type == "NOTIFICATION",
                        OutboxTask.task_key.in_(
                            [
                                f"maintenance:manager:{plan_id}:{due_date.isoformat()}:{manager.id}",
                                f"maintenance:impact:{plan_id}:{reservation.created[0].id}:{due_date.isoformat()}",
                            ]
                        ),
                    )
                )
            ).all()
        )
        assert plan is not None and plan.due_notice_sent_at is not None
        assert {task.payload["user_id"] for task in notifications} == {student.id, manager.id}
        assert any("预约受维护到期影响" == task.payload["title"] for task in notifications)
        stored_reservation = await session.get(Reservation, reservation.created[0].id)
        assert stored_reservation is not None and stored_reservation.status == "APPROVED"
        assert len(notifications) == 2
        assert len({task.task_key for task in notifications}) == 2


@pytest.mark.asyncio
async def test_failed_routine_maintenance_notification_uses_correct_type(seeded) -> None:
    factory, _, _, _, _, manager, device, _ = seeded
    async with factory() as session:
        plan = await MaintenanceService(session, principal(manager, "LAB_ADMIN")).create_plan(
            device.id,
            MaintenancePlanWrite(
                plan_type="ROUTINE",
                title="年度清洁保养",
                interval_value=1,
                interval_unit="YEAR",
                due_date=date.today(),
            ),
        )
        record = await MaintenanceService(
            session, principal(manager, "LAB_ADMIN")
        ).complete_cycle(
            plan.id,
            MaintenanceRecordCreate(
                cycle_due_date=plan.due_date,
                completed_date=date.today(),
                result="FAILED",
                notes="冷却风扇异常",
            ),
            idempotency_key="routine-maintenance-failed-0001",
        )
        notification = await session.scalar(
            select(OutboxTask).where(
                OutboxTask.task_key == f"repair:{record.repair_report_id}:maintenance-failure"
            )
        )
        assert notification is not None
        assert notification.payload["title"] == "保养未通过，已创建报修工单"
        assert "保养计划“年度清洁保养”未通过" in notification.payload["content"]
        assert "校准未通过" not in notification.payload["content"]


@pytest.mark.asyncio
async def test_due_outbox_falls_back_when_manager_is_inactive(seeded) -> None:
    factory, _, _, _, _, manager, device, _ = seeded
    async with factory() as session:
        inactive_manager = await session.get(User, manager.id)
        assert inactive_manager is not None
        inactive_manager.status = 0
        sys_admin = User(
            username="system-admin-for-maintenance-test",
            password_hash="test",
            real_name="系统管理员",
            status=1,
        )
        sys_admin_role = await session.scalar(select(Role).where(Role.role_code == "SYS_ADMIN"))
        assert sys_admin_role is not None
        sys_admin.roles.append(sys_admin_role)
        plan = DeviceMaintenancePlan(
            device_id=device.id,
            college_id=device.college_id,
            plan_type="ROUTINE",
            title="设备周期保养",
            interval_value=1,
            interval_unit="YEAR",
            due_date=date.today(),
            active=True,
            created_by=manager.id,
            updated_by=manager.id,
        )
        session.add_all([sys_admin, plan])
        await session.commit()
        plan_id = plan.id
        sys_admin_id = sys_admin.id

    app = FastAPI()
    app.state.settings = Settings(environment="test", cors_origins=[], enable_workers=False)
    app.state.session_factory = factory
    await OutboxWorker(app)._handle(
        "MAINTENANCE_DUE",
        {"plan_id": plan_id, "due_date": date.today().isoformat()},
        task_key="maintenance-due-inactive-manager-0001",
    )

    async with factory() as session:
        notifications = list(
            (
                await session.scalars(
                    select(OutboxTask).where(
                        OutboxTask.task_type == "NOTIFICATION",
                        OutboxTask.task_key
                        == (
                            f"maintenance:manager:{plan_id}:"
                            f"{date.today().isoformat()}:{sys_admin_id}"
                        ),
                    )
                )
            ).all()
        )
        assert {task.payload["user_id"] for task in notifications} == {sys_admin_id}


def test_maintenance_interval_handles_days_month_end_and_years() -> None:
    assert add_interval(date(2026, 1, 30), 2, "DAY") == date(2026, 2, 1)
    assert add_interval(date(2026, 1, 31), 1, "MONTH") == date(2026, 2, 28)
    assert add_interval(date(2024, 2, 29), 1, "YEAR") == date(2025, 2, 28)


@pytest.mark.asyncio
async def test_maintenance_authorization_and_system_admin_list_scope(seeded) -> None:
    factory, _, _, student, other_student, manager, device, _ = seeded
    async with factory() as session:
        manager_service = MaintenanceService(session, principal(manager, "LAB_ADMIN"))
        plan = await manager_service.create_plan(
            device.id,
            MaintenancePlanWrite(
                plan_type="ROUTINE",
                title="授权范围验证",
                interval_value=1,
                interval_unit="YEAR",
                due_date=date.today() + timedelta(days=10),
                active=False,
            ),
        )

        with pytest.raises(ApiError) as device_error:
            await MaintenanceService(session, principal(student, "STUDENT"))._managed_device(
                device.id
            )
        assert device_error.value.code == "FORBIDDEN"

        with pytest.raises(ApiError) as plan_error:
            await MaintenanceService(
                session, principal(other_student, "LAB_ADMIN")
            ).get_plan(plan.id)
        assert plan_error.value.code == "MAINTENANCE_PLAN_NOT_FOUND"

        with pytest.raises(ApiError) as permission_error:
            await MaintenanceService(session, principal(student, "STUDENT")).list_plans()
        assert permission_error.value.code == "FORBIDDEN"

        global_admin = Principal(
            user_id=manager.id,
            username=manager.username,
            college_id=None,
            roles=("SYS_ADMIN",),
            token_type="access",
            token_id="global-maintenance-reader",
        )
        global_page = await MaintenanceService(session, global_admin).list_plans()
        assert {item.id for item in global_page.items} == {plan.id}


@pytest.mark.asyncio
async def test_maintenance_locked_device_disappearance_is_reported(seeded, monkeypatch) -> None:
    factory, _, _, _, _, manager, device, _ = seeded
    async with factory() as session:
        monkeypatch.setattr(
            ReservationService, "_load_device", AsyncMock(return_value=device)
        )
        monkeypatch.setattr(
            ReservationService, "_can_manage_device", AsyncMock(return_value=True)
        )
        monkeypatch.setattr(session, "scalar", AsyncMock(return_value=None))
        service = MaintenanceService(session, principal(manager, "LAB_ADMIN"))
        with pytest.raises(ApiError) as error:
            await service._managed_device(device.id, lock=True)
        assert error.value.code == "DEVICE_NOT_FOUND"


@pytest.mark.asyncio
async def test_maintenance_plan_activation_checks_free_downtime_and_schedules_due_task(
    seeded, monkeypatch
) -> None:
    factory, _, _, _, _, manager, device, _ = seeded
    sync_bump = AsyncMock()
    monkeypatch.setattr(maintenance_module, "sync_catalog_cache_bump", sync_bump)
    async with factory() as session:
        service = MaintenanceService(session, principal(manager, "LAB_ADMIN"), app=FastAPI())
        inactive = await service.create_plan(
            device.id,
            MaintenancePlanWrite(
                plan_type="ROUTINE",
                title="待启用维护计划",
                interval_value=1,
                interval_unit="MONTH",
                due_date=date.today() + timedelta(days=30),
                active=False,
            ),
        )
        assert sync_bump.await_count == 1

        activated = await service.update_plan(
            inactive.id,
            MaintenancePlanWrite(
                plan_type="CALIBRATION",
                title="已启用校准计划",
                interval_value=1,
                interval_unit="YEAR",
                due_date=date.today() - timedelta(days=1),
                downtime_start=date.today() + timedelta(days=20),
                downtime_end=date.today() + timedelta(days=21),
                active=True,
            ),
        )
        assert activated.active is True
        assert activated.plan_type == "CALIBRATION"
        tasks = list(
            (
                await session.scalars(
                    select(OutboxTask).where(
                        OutboxTask.task_type == "MAINTENANCE_DUE",
                        OutboxTask.payload["plan_id"].as_integer() == inactive.id,
                    )
                )
            ).all()
        )
        assert len(tasks) == 1
        assert tasks[0].execute_at <= utcnow_naive() + timedelta(seconds=2)
        assert sync_bump.await_count == 2

        # A title-only edit with the same due date and active state should not
        # enqueue a duplicate due notification.
        await service.update_plan(
            inactive.id,
            MaintenancePlanWrite(
                plan_type="CALIBRATION",
                title="标题调整后的校准计划",
                interval_value=1,
                interval_unit="YEAR",
                due_date=activated.due_date,
                downtime_start=activated.downtime_start,
                downtime_end=activated.downtime_end,
                active=True,
            ),
        )
        tasks_after_edit = list(
            (
                await session.scalars(
                    select(OutboxTask).where(
                        OutboxTask.task_type == "MAINTENANCE_DUE",
                        OutboxTask.payload["plan_id"].as_integer() == inactive.id,
                    )
                )
            ).all()
        )
        assert len(tasks_after_edit) == 1

        no_app_service = MaintenanceService(session, principal(manager, "LAB_ADMIN"))
        no_app_update = await no_app_service.update_plan(
            inactive.id,
            MaintenancePlanWrite(
                plan_type="CALIBRATION",
                title="不触发外部缓存同步",
                interval_value=1,
                interval_unit="YEAR",
                due_date=activated.due_date,
                downtime_start=activated.downtime_start,
                downtime_end=activated.downtime_end,
                active=True,
            ),
        )
        assert no_app_update.title == "不触发外部缓存同步"


@pytest.mark.asyncio
async def test_inactive_maintenance_cycle_validates_inputs_and_prevents_duplicate_cycle(
    seeded,
) -> None:
    factory, _, _, _, _, manager, device, _ = seeded
    async with factory() as session:
        service = MaintenanceService(session, principal(manager, "LAB_ADMIN"))
        plan = await service.create_plan(
            device.id,
            MaintenancePlanWrite(
                plan_type="ROUTINE",
                title="停用计划执行验证",
                interval_value=1,
                interval_unit="MONTH",
                due_date=date.today(),
                active=False,
            ),
        )
        valid = MaintenanceRecordCreate(
            cycle_due_date=plan.due_date,
            completed_date=date.today(),
            result="PASSED",
            notes="维护检查通过",
        )

        with pytest.raises(ApiError) as key_error:
            await service.complete_cycle(plan.id, valid, idempotency_key="short")
        assert key_error.value.code == "IDEMPOTENCY_KEY_INVALID"

        with pytest.raises(ApiError) as asset_error:
            await service.complete_cycle(
                plan.id,
                valid.model_copy(update={"evidence_asset_token": "missing-evidence-token-0001"}),
                idempotency_key="missing-maintenance-proof-0001",
            )
        assert asset_error.value.code == "EVIDENCE_NOT_FOUND"

        with pytest.raises(ApiError) as future_error:
            await service.complete_cycle(
                plan.id,
                valid.model_copy(update={"completed_date": date.today() + timedelta(days=1)}),
                idempotency_key="future-maintenance-date-0001",
            )
        assert future_error.value.code == "MAINTENANCE_DATE_INVALID"

        with pytest.raises(ApiError) as stale_cycle_error:
            await service.complete_cycle(
                plan.id,
                valid.model_copy(update={"cycle_due_date": plan.due_date - timedelta(days=1)}),
                idempotency_key="stale-maintenance-cycle-0001",
            )
        assert stale_cycle_error.value.code == "MAINTENANCE_CYCLE_CHANGED"

        completed = await service.complete_cycle(
            plan.id, valid, idempotency_key="inactive-maintenance-cycle-0001"
        )
        assert completed.result == "PASSED"
        assert not (
            await session.scalars(
                select(OutboxTask).where(
                    OutboxTask.task_type == "MAINTENANCE_DUE",
                    OutboxTask.payload["plan_id"].as_integer() == plan.id,
                )
            )
        ).all()

        # Simulate a stale due-date snapshot after a completed write. The
        # duplicate-cycle guard must still prevent recording the same cycle.
        stored_plan = await session.get(DeviceMaintenancePlan, plan.id)
        assert stored_plan is not None
        stored_plan.due_date = valid.cycle_due_date
        await session.commit()

        with pytest.raises(ApiError) as duplicate_cycle_error:
            await service.complete_cycle(
                plan.id,
                valid,
                idempotency_key="different-maintenance-cycle-key-0001",
            )
        assert duplicate_cycle_error.value.code == "MAINTENANCE_CYCLE_ALREADY_COMPLETED"


@pytest.mark.asyncio
async def test_failed_maintenance_cycle_cannot_be_retested_until_repair_is_closed(seeded) -> None:
    factory, _, _, _, _, manager, device, _ = seeded
    async with factory() as session:
        service = MaintenanceService(session, principal(manager, "LAB_ADMIN"))
        plan = await service.create_plan(
            device.id,
            MaintenancePlanWrite(
                plan_type="ROUTINE",
                title="待维修闭环的维护计划",
                interval_value=1,
                interval_unit="YEAR",
                due_date=date.today(),
            ),
        )
        failed = MaintenanceRecordCreate(
            cycle_due_date=plan.due_date,
            completed_date=date.today(),
            result="FAILED",
            notes="检查发现风扇异常",
        )
        await service.complete_cycle(
            plan.id, failed, idempotency_key="failed-cycle-with-open-repair-0001"
        )
        with pytest.raises(ApiError) as error:
            await service.complete_cycle(
                plan.id,
                failed.model_copy(update={"notes": "再次检测风扇异常"}),
                idempotency_key="failed-cycle-premature-retest-0001",
            )
        assert error.value.code == "MAINTENANCE_REPAIR_NOT_COMPLETED"
