from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.application.repairs import RepairService
from app.application.reservations import ReservationService
from app.auth.security import Principal
from app.core.errors import ApiError
from app.infrastructure.db.models import Device, OutboxTask, RepairReport
from sqlalchemy import select


def _principal(user, *roles: str, permissions: tuple[str, ...] | None = None) -> Principal:
    defaults = {
        "STUDENT": ("repair:create", "repair:read:own", "repair:confirm"),
        "LAB_ADMIN": ("repair:read:scope", "repair:handle"),
    }
    granted = permissions or tuple(code for role in roles for code in defaults.get(role, ()))
    return Principal(
        user_id=user.id,
        username=user.username,
        college_id=user.college_id,
        roles=roles,
        token_type="access",
        token_id="repair-failure-coverage",
        permissions=granted,
    )


async def _create(service: RepairService, device_id: int) -> int:
    report = await service.create(
        device_id=device_id,
        title="覆盖率边界报修",
        description="验证状态和权限保护",
        image_urls=None,
    )
    return report.id


@pytest.mark.asyncio
async def test_repair_create_rejects_permission_missing_unknown_device_and_bad_priority(
    seeded, monkeypatch
) -> None:
    factory, _, _, student, _, _, device, _ = seeded
    async with factory() as session:
        denied = RepairService(
            session,
            _principal(student, "STUDENT", permissions=("device:read",)),
        )
        with pytest.raises(ApiError, match="没有提交报修"):
            await _create(denied, device.id)

        allowed = RepairService(session, _principal(student, "STUDENT"))
        with pytest.raises(ApiError) as missing:
            await _create(allowed, 999999)
        assert missing.value.code == "DEVICE_NOT_FOUND"

        with pytest.raises(ApiError) as priority:
            await allowed.create(
                device_id=device.id,
                title="无效优先级",
                description=None,
                image_urls=None,
                priority="CRITICAL",
            )
        assert priority.value.code == "REPAIR_PRIORITY_INVALID"

        monkeypatch.setattr(
            ReservationService,
            "_load_device",
            AsyncMock(return_value=device),
        )
        monkeypatch.setattr(session, "scalar", AsyncMock(return_value=None))
        with pytest.raises(ApiError) as disappeared:
            await _create(allowed, device.id)
        assert disappeared.value.code == "DEVICE_NOT_FOUND"


@pytest.mark.asyncio
async def test_repair_create_rejects_retired_device_and_preserves_disabled_device(seeded) -> None:
    factory, _, _, student, _, _, device, _ = seeded
    async with factory() as session:
        stored = await session.get(Device, device.id)
        assert stored is not None
        stored.status = "RETIRED"
        await session.commit()

    async with factory() as session:
        with pytest.raises(ApiError) as retired:
            await _create(RepairService(session, _principal(student, "STUDENT")), device.id)
        assert retired.value.code == "DEVICE_NOT_REPAIRABLE"

    async with factory() as session:
        stored = await session.get(Device, device.id)
        assert stored is not None
        stored.status = "DISABLED"
        await session.commit()

    async with factory() as session:
        service = RepairService(session, _principal(student, "STUDENT"))
        report_id = await _create(service, device.id)
        stored = await session.get(Device, device.id)
        assert stored is not None and stored.status == "DISABLED"
        assert report_id > 0


@pytest.mark.asyncio
async def test_repair_load_scope_and_list_permission_validation(seeded) -> None:
    factory, _, _, student, _, _, device, _ = seeded
    async with factory() as session:
        report_id = await _create(RepairService(session, _principal(student, "STUDENT")), device.id)

    async with factory() as session:
        out_of_scope = Principal(
            user_id=student.id,
            username=student.username,
            college_id=student.college_id + 100,
            roles=("LAB_ADMIN",),
            token_type="access",
            token_id="wrong-tenant",
            permissions=("repair:read:scope", "repair:handle"),
        )
        with pytest.raises(ApiError) as hidden:
            await RepairService(session, out_of_scope)._load(report_id)
        assert hidden.value.status_code == 404
        with pytest.raises(ApiError) as missing:
            await RepairService(session, _principal(student, "STUDENT"))._load(999999)
        assert missing.value.status_code == 404

        denied = RepairService(
            session,
            _principal(student, "STUDENT", permissions=("device:read",)),
        )
        with pytest.raises(ApiError):
            await denied.mine()
        with pytest.raises(ApiError):
            await denied.managed()

        manager = RepairService(
            session,
            _principal(student, "STUDENT", permissions=("repair:handle",)),
        )
        with pytest.raises(ApiError) as invalid_status:
            await manager.managed(status="UNKNOWN")
        assert invalid_status.value.code == "REPAIR_STATUS_INVALID"

        system_admin = _principal(
            student,
            "SYS_ADMIN",
            permissions=("repair:read:own", "repair:handle"),
        )
        await RepairService(session, system_admin).mine()
        await RepairService(session, system_admin).managed(status="PENDING")
        await RepairService(session, system_admin).managed()


@pytest.mark.asyncio
async def test_repair_take_and_finish_reject_wrong_state_and_handler(seeded, monkeypatch) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    student_principal = _principal(student, "STUDENT")
    manager_principal = _principal(manager, "LAB_ADMIN")
    async with factory() as session:
        report_id = await _create(RepairService(session, student_principal), device.id)

    async with factory() as session:
        denied = RepairService(
            session,
            _principal(manager, "LAB_ADMIN", permissions=("repair:read:scope",)),
        )
        with pytest.raises(ApiError):
            await denied.take(report_id)

        cannot_manage = RepairService(session, manager_principal)
        monkeypatch.setattr(cannot_manage, "_can_manage", AsyncMock(return_value=False))
        with pytest.raises(ApiError) as scope_error:
            await cannot_manage.take(report_id)
        assert scope_error.value.status_code == 403

    async with factory() as session:
        manager_service = RepairService(session, manager_principal)
        no_handle_permission = RepairService(
            session,
            _principal(manager, "LAB_ADMIN", permissions=("repair:read:scope",)),
        )
        with pytest.raises(ApiError):
            await no_handle_permission.resolve(report_id, "缺少维修处理权限")
        with pytest.raises(ApiError) as wrong_state:
            await manager_service.resolve(report_id, "尚未受理不能直接完成")
        assert wrong_state.value.code == "INVALID_REPAIR_STATE"

        with pytest.raises(ApiError):
            await RepairService(
                session,
                _principal(manager, "LAB_ADMIN", permissions=("repair:read:scope",)),
            ).take(report_id)

        original_execute = session.execute

        async def lose_take_race(statement, *args, **kwargs):
            if getattr(statement, "is_update", False):
                return SimpleNamespace(rowcount=0)
            return await original_execute(statement, *args, **kwargs)

        monkeypatch.setattr(session, "execute", lose_take_race)
        with pytest.raises(ApiError) as race:
            await manager_service.take(report_id)
        assert race.value.code == "REPAIR_STATE_CHANGED"

    async with factory() as session:
        manager_service = RepairService(session, manager_principal)

        await manager_service.take(report_id)
        with pytest.raises(ApiError) as wrong_state_after_take:
            await manager_service.take(report_id)
        assert wrong_state_after_take.value.code == "INVALID_REPAIR_STATE"

    async with factory() as session:
        other_manager = Principal(
            user_id=manager.id + 100,
            username="different-manager",
            college_id=manager.college_id,
            roles=("LAB_ADMIN",),
            token_type="access",
            token_id="other-handler",
            permissions=("repair:handle", "repair:read:scope"),
        )
        service = RepairService(session, other_manager)
        monkeypatch.setattr(service, "_can_manage", AsyncMock(return_value=True))
        with pytest.raises(ApiError) as mismatch:
            await service.resolve(report_id, "其他负责人不能修改该工单")
        assert mismatch.value.code == "REPAIR_HANDLER_MISMATCH"

        unable_to_manage = RepairService(session, manager_principal)
        monkeypatch.setattr(unable_to_manage, "_can_manage", AsyncMock(return_value=False))
        with pytest.raises(ApiError) as forbidden:
            await unable_to_manage.resolve(report_id, "非负责人不能操作")
        assert forbidden.value.status_code == 403


@pytest.mark.asyncio
async def test_repair_take_and_finish_detect_conditional_update_races(seeded, monkeypatch) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    async with factory() as session:
        report_id = await _create(RepairService(session, _principal(student, "STUDENT")), device.id)
    async with factory() as session:
        service = RepairService(session, _principal(manager, "LAB_ADMIN"))
        await service.take(report_id)

    async with factory() as session:
        service = RepairService(session, _principal(manager, "LAB_ADMIN"))
        original_execute = session.execute

        async def lose_finish_race(statement, *args, **kwargs):
            if getattr(statement, "is_update", False):
                return SimpleNamespace(rowcount=0)
            return await original_execute(statement, *args, **kwargs)

        monkeypatch.setattr(session, "execute", lose_finish_race)
        with pytest.raises(ApiError) as race:
            await service.resolve(report_id, "并发状态发生变化")
        assert race.value.code == "REPAIR_STATE_CHANGED"


@pytest.mark.asyncio
async def test_repair_take_without_resolve_deadline_does_not_enqueue_sla(seeded) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    async with factory() as session:
        report_id = await _create(RepairService(session, _principal(student, "STUDENT")), device.id)
        report = await session.get(RepairReport, report_id)
        assert report is not None
        report.resolve_due_at = None
        await session.commit()

    async with factory() as session:
        await RepairService(session, _principal(manager, "LAB_ADMIN")).take(report_id)
        task = await session.scalar(
            select(OutboxTask).where(
                OutboxTask.task_key == f"repair:{report_id}:sla-resolve"
            )
        )
        assert task is None


@pytest.mark.asyncio
async def test_repair_confirm_guards_and_conditional_update_race(seeded, monkeypatch) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    async with factory() as session:
        report_id = await _create(RepairService(session, _principal(student, "STUDENT")), device.id)
    async with factory() as session:
        with pytest.raises(ApiError) as not_resolved:
            await RepairService(session, _principal(student, "STUDENT")).confirm(
                report_id,
                confirmed=True,
            )
        assert not_resolved.value.code == "INVALID_REPAIR_STATE"

        await RepairService(session, _principal(manager, "LAB_ADMIN")).take(report_id)
        await RepairService(session, _principal(manager, "LAB_ADMIN")).resolve(
            report_id,
            "已完成修复",
        )

    async with factory() as session:
        no_permission = RepairService(
            session,
            _principal(student, "STUDENT", permissions=("repair:read:own",)),
        )
        with pytest.raises(ApiError):
            await no_permission.confirm(report_id, confirmed=True)

        other_student = Principal(
            user_id=student.id + 100,
            username="other-student",
            college_id=student.college_id,
            roles=("STUDENT",),
            token_type="access",
            token_id="not-reporter",
            permissions=("repair:confirm",),
        )
        with pytest.raises(ApiError) as owner_error:
            await RepairService(session, other_student).confirm(report_id, confirmed=True)
        assert owner_error.value.code == "FORBIDDEN"

        original_execute = session.execute

        async def lose_update_race(statement, *args, **kwargs):
            if getattr(statement, "is_update", False):
                return SimpleNamespace(rowcount=0)
            return await original_execute(statement, *args, **kwargs)

        monkeypatch.setattr(session, "execute", lose_update_race)
        with pytest.raises(ApiError) as race:
            await RepairService(session, _principal(student, "STUDENT")).confirm(
                report_id,
                confirmed=True,
            )
        assert race.value.code == "REPAIR_STATE_CHANGED"


@pytest.mark.asyncio
async def test_repair_confirmation_without_autoclose_task_and_worklog_visibility(
    seeded, monkeypatch
) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    async with factory() as session:
        report_id = await _create(RepairService(session, _principal(student, "STUDENT")), device.id)
    async with factory() as session:
        await RepairService(session, _principal(manager, "LAB_ADMIN")).take(report_id)
        await RepairService(session, _principal(manager, "LAB_ADMIN")).resolve(report_id, "已维修")
        task = await session.scalar(
            select(OutboxTask).where(OutboxTask.task_key == f"repair:{report_id}:auto-close")
        )
        assert task is not None
        await session.delete(task)
        await session.commit()

    async with factory() as session:
        logs_service = RepairService(
            session,
            _principal(manager, "LAB_ADMIN", permissions=("repair:read:scope",)),
        )
        monkeypatch.setattr(logs_service, "_can_manage", AsyncMock(return_value=False))
        with pytest.raises(ApiError) as hidden:
            await logs_service.worklogs(report_id)
        assert hidden.value.status_code == 404

    async with factory() as session:
        result = await RepairService(session, _principal(student, "STUDENT")).confirm(
            report_id,
            confirmed=True,
        )
        assert result.status == "COMPLETED"


@pytest.mark.asyncio
async def test_confirmed_repair_keeps_device_in_maintenance_while_another_report_is_open(
    seeded,
) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    async with factory() as session:
        service = RepairService(session, _principal(student, "STUDENT"))
        first_report = await _create(service, device.id)
        second_report = await _create(service, device.id)

    async with factory() as session:
        manager_service = RepairService(session, _principal(manager, "LAB_ADMIN"))
        await manager_service.take(first_report)
        await manager_service.resolve(first_report, "第一张工单处理完成")

    async with factory() as session:
        result = await RepairService(session, _principal(student, "STUDENT")).confirm(
            first_report,
            confirmed=True,
        )
        current_device = await session.get(Device, device.id)
        assert result.status == "COMPLETED"
        assert current_device is not None and current_device.status == "MAINTENANCE"
        pending = await session.get(RepairReport, second_report)
        assert pending is not None and pending.status == "PENDING"


def test_repair_sla_dictionary_configuration_is_clamped() -> None:
    app = SimpleNamespace(
        state=SimpleNamespace(
            settings=SimpleNamespace(repair_sla_days={"URGENT": 0, "NORMAL": 5})
        )
    )
    service = RepairService(None, None, app=app)  # type: ignore[arg-type]
    assert service._sla_days("URGENT") == 1
    assert service._sla_days("IMPORTANT") == 5
