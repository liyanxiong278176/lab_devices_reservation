from datetime import date, timedelta

import pytest
from app.api.v2.catalog import list_colleges, list_labs
from app.api.v2.dashboard import dashboard_me, dashboard_overview
from app.application.repairs import RepairService
from app.auth.security import Principal
from app.core.errors import ApiError
from app.infrastructure.db.models import OutboxTask, RepairReport, RepairWorklog, Reservation
from sqlalchemy import select


def principal(user, *roles: str) -> Principal:
    return Principal(
        user_id=user.id,
        username=user.username,
        college_id=user.college_id,
        roles=roles,
        token_type="access",
        token_id=f"test-{user.id}",
    )


@pytest.mark.asyncio
async def test_repair_scope_and_lifecycle(seeded) -> None:
    factory, _, _, student1, student2, manager, device, _ = seeded
    async with factory() as session:
        created = await RepairService(session, principal(student1, "STUDENT")).create(
            device_id=device.id,
            title="工作站无法启动",
            description="按电源键无反应",
            image_urls=None,
        )
        assert created.status == "PENDING"
        assert created.created_at is not None

    async with factory() as session:
        report = await session.scalar(select(RepairReport).where(RepairReport.id == created.id))
        assert report is not None
        assert report.status == "PENDING"

        # A manager from another college cannot even load or operate this ticket.
        with pytest.raises(ApiError) as error:
            await RepairService(session, principal(student2, "STUDENT")).take(created.id)
        assert error.value.status_code == 404

    async with factory() as session:
        taken = await RepairService(session, principal(manager, "LAB_ADMIN")).take(created.id)
        assert taken.status == "PROCESSING"
        resolved = await RepairService(session, principal(manager, "LAB_ADMIN")).resolve(
            created.id,
            "更换电源模块后恢复正常",
        )
        assert resolved.status == "RESOLVED"
        assert resolved.resolution_note == "更换电源模块后恢复正常"

    async with factory() as session:
        confirmed = await RepairService(session, principal(student1, "STUDENT")).confirm(
            created.id,
            confirmed=True,
            note="用户现场确认设备已恢复正常",
        )
        assert confirmed.status == "COMPLETED"
        assert confirmed.user_confirmed_at is not None

    async with factory() as session:
        report = await session.scalar(select(RepairReport).where(RepairReport.id == created.id))
        assert report is not None and report.status == "COMPLETED"


@pytest.mark.asyncio
async def test_repair_create_respects_college_boundary(seeded) -> None:
    factory, _, _, student1, _, _, _, other_device = seeded
    async with factory() as session:
        with pytest.raises(ApiError) as error:
            await RepairService(session, principal(student1, "STUDENT")).create(
                device_id=other_device.id,
                title="跨学院设备报修",
                description="不应被允许",
                image_urls=None,
            )
        assert error.value.code == "DEVICE_NOT_FOUND"


@pytest.mark.asyncio
async def test_manager_can_reject_a_pending_repair(seeded) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    async with factory() as session:
        created = await RepairService(session, principal(student, "STUDENT")).create(
            device_id=device.id,
            title="设备无法启动",
            description="开机无响应",
            image_urls=None,
        )

    async with factory() as session:
        rejected = await RepairService(session, principal(manager, "LAB_ADMIN")).reject(
            created.id,
            "经核实为操作问题，不属于设备故障",
        )

    assert rejected.status == "REJECTED"
    assert rejected.resolution_note == "经核实为操作问题，不属于设备故障"
    async with factory() as session:
        worklogs = list(
            (
                await session.scalars(
                    select(RepairWorklog)
                    .where(RepairWorklog.report_id == created.id)
                    .order_by(RepairWorklog.id)
                )
            ).all()
        )
        assert [worklog.status for worklog in worklogs] == ["PENDING", "REJECTED"]


@pytest.mark.asyncio
async def test_reopened_repair_can_be_resolved_again_without_duplicate_outbox_keys(seeded) -> None:
    factory, _, _, student, _, manager, device, _ = seeded
    async with factory() as session:
        created = await RepairService(session, principal(student, "STUDENT")).create(
            device_id=device.id,
            title="设备间歇性断电",
            description="使用中会突然关机",
            image_urls=None,
        )

    async with factory() as session:
        await RepairService(session, principal(manager, "LAB_ADMIN")).take(created.id)
    async with factory() as session:
        await RepairService(session, principal(manager, "LAB_ADMIN")).resolve(
            created.id,
            "更换电源后完成初次处理",
        )

    task_key = f"repair:{created.id}:auto-close"
    async with factory() as session:
        original_task = await session.scalar(
            select(OutboxTask).where(OutboxTask.task_key == task_key)
        )
        assert original_task is not None
        original_task_id = original_task.id
        original_deadline = original_task.execute_at

    async with factory() as session:
        reopened = await RepairService(session, principal(student, "STUDENT")).confirm(
            created.id,
            confirmed=False,
            note="问题仍然存在",
        )
        assert reopened.status == "PROCESSING"

    async with factory() as session:
        cancelled_task = await session.scalar(
            select(OutboxTask).where(OutboxTask.task_key == task_key)
        )
        assert cancelled_task is not None
        assert cancelled_task.status == "CANCELLED"

    async with factory() as session:
        resolved_again = await RepairService(
            session,
            principal(manager, "LAB_ADMIN"),
        ).resolve(created.id, "重新检修后完成处理")
        assert resolved_again.status == "RESOLVED"

    async with factory() as session:
        reset_task = await session.scalar(select(OutboxTask).where(OutboxTask.task_key == task_key))
        assert reset_task is not None
        assert reset_task.id == original_task_id
        assert reset_task.status == "PENDING"
        assert reset_task.attempts == 0
        assert reset_task.execute_at >= original_deadline
        notification_keys = list(
            (
                await session.scalars(
                    select(OutboxTask.task_key).where(
                        OutboxTask.task_type == "NOTIFICATION",
                        OutboxTask.aggregate_key == f"repair:{created.id}",
                    )
                )
            ).all()
        )
        assert len(notification_keys) == 5
        assert len(notification_keys) == len(set(notification_keys))


@pytest.mark.asyncio
async def test_dashboard_is_scoped_and_uses_day_granularity(seeded) -> None:
    factory, _, _, student1, _, manager, _, _ = seeded
    async with factory() as session:
        mine = await dashboard_me(principal(student1, "STUDENT"), session)
        assert mine.data is not None
        assert "myTrend30d" in mine.data

        overview = await dashboard_overview(
            group_by="device",
            days=30,
            principal=principal(manager, "LAB_ADMIN"),
            session=session,
        )
        assert overview.data is not None
        assert overview.data["utilization"][0]["availableSlots"] == 30


@pytest.mark.asyncio
async def test_dashboard_overview_heatmap_uses_reservation_date(seeded) -> None:
    factory, college, _, student1, _, manager, device, _ = seeded
    async with factory() as session:
        session.add(
            Reservation(
                college_id=college.id,
                user_id=student1.id,
                device_id=device.id,
                purpose="仪表盘回归测试",
                start_date=date.today(),
                end_date=date.today(),
                status="APPROVED",
            )
        )
        await session.commit()

    async with factory() as session:
        overview = await dashboard_overview(
            group_by="device",
            days=30,
            principal=principal(manager, "LAB_ADMIN"),
            session=session,
        )

    assert overview.data is not None
    assert overview.data["heatmap"] == [
        {
            "dayOfWeek": ((date.today().weekday() + 1) % 7) + 1,
            "hour": 0,
            "count": 1,
        }
    ]


@pytest.mark.asyncio
async def test_dashboard_pending_approvals_includes_future_reservations(seeded) -> None:
    factory, college, _, student1, _, manager, device, _ = seeded
    device.need_approval = True
    future_day = date.today() + timedelta(days=45)
    async with factory() as session:
        session.add(device)
        session.add(
            Reservation(
                college_id=college.id,
                user_id=student1.id,
                device_id=device.id,
                purpose="未来预约审批统计",
                start_date=future_day,
                end_date=future_day,
                status="PENDING",
            )
        )
        await session.commit()

    async with factory() as session:
        overview = await dashboard_overview(
            group_by="device",
            days=30,
            principal=principal(manager, "LAB_ADMIN"),
            session=session,
        )

    assert overview.data is not None
    assert overview.data["cards"]["pendingApprovals"] == 1


@pytest.mark.asyncio
async def test_manager_catalog_is_tenant_and_manager_scoped(seeded) -> None:
    factory, college, _, student1, _, manager, _, _ = seeded
    async with factory() as session:
        manager_principal = principal(manager, "LAB_ADMIN")
        colleges = await list_colleges(manager_principal, session)
        labs = await list_labs(1, 100, manager_principal, session)
        global_labs = await list_labs(1, 100, principal(student1, "SYS_ADMIN"), session)

    assert colleges.data is not None
    assert [item.id for item in colleges.data] == [college.id]
    assert labs.data is not None
    assert labs.data["total"] == 1
    assert global_labs.data is not None
    assert global_labs.data["total"] >= 1
