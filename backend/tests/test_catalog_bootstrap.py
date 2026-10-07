from datetime import date, timedelta

import pytest
from app.infrastructure.db.catalog_bootstrap import seed_initial_catalog
from app.infrastructure.db.models import (
    AuditLog,
    College,
    Device,
    DeviceCategory,
    DeviceMaintenancePlan,
    DeviceMaintenanceRecord,
    DevicePool,
    DeviceStatusHistory,
    Lab,
    OutboxTask,
    Role,
    User,
)
from sqlalchemy import func, select

TODAY = date(2026, 10, 7)


async def add_admin(factory):
    async with factory() as session:
        role = Role(role_code="SYS_ADMIN", role_name="系统管理员")
        admin = User(username="operator", password_hash="existing-hash", status=1, roles=[role])
        session.add(admin)
        await session.commit()
        return admin.id


async def counts(factory):
    async with factory() as session:
        return {
            model.__tablename__: await session.scalar(select(func.count()).select_from(model))
            for model in (
                College,
                Lab,
                DeviceCategory,
                Device,
                DevicePool,
                DeviceMaintenancePlan,
                DeviceMaintenanceRecord,
                DeviceStatusHistory,
                AuditLog,
                OutboxTask,
                User,
            )
        }


async def test_seed_empty_catalog_is_repeatable_and_creates_real_reminder_tasks(session_factory):
    actor_id = await add_admin(session_factory)
    engine = session_factory.kw["bind"]
    first = await seed_initial_catalog(engine, today=TODAY)
    assert first == dict(colleges=3, labs=3, categories=5, devices=18, plans=18, skipped_devices=0)
    before = await counts(session_factory)
    second = await seed_initial_catalog(engine, today=TODAY + timedelta(days=100))
    assert second == dict(colleges=0, labs=0, categories=0, devices=0, plans=0, skipped_devices=18)
    assert await counts(session_factory) == before
    async with session_factory() as session:
        devices = list((await session.scalars(select(Device))).all())
        assert all(d.status == "IDLE" and "示例" in d.name and d.pool_id for d in devices)
        plans = list((await session.scalars(select(DeviceMaintenancePlan))).all())
        assert {p.plan_type for p in plans} == {"ROUTINE", "CALIBRATION", "SAFETY_CHECK"}
        assert all(p.due_date > TODAY and p.created_by == actor_id for p in plans)
        assert all(p.downtime_start is None and p.downtime_end is None for p in plans)
        tasks = list((await session.scalars(select(OutboxTask))).all())
        assert len([t for t in tasks if t.task_type == "MAINTENANCE_DUE"]) == 18
        assert len([t for t in tasks if t.task_type == "CACHE_BUMP"]) == 18
        assert await session.scalar(select(func.count()).select_from(DeviceMaintenanceRecord)) == 0
        assert (await session.get(User, actor_id)).password_hash == "existing-hash"


async def test_redeploy_preserves_edited_devices_plans_and_disabled_colleges(session_factory):
    await add_admin(session_factory)
    engine = session_factory.kw["bind"]
    await seed_initial_catalog(engine, today=TODAY)
    async with session_factory() as session:
        device = await session.scalar(select(Device).where(Device.asset_code == "LF-INIT-CS-OSC"))
        plan = await session.scalar(
            select(DeviceMaintenancePlan).where(DeviceMaintenancePlan.device_id == device.id)
        )
        college = await session.get(College, device.college_id)
        lab = await session.get(Lab, device.lab_id)
        device.name, device.status = "管理员修改后的设备", "MAINTENANCE"
        plan.title, plan.active, plan.due_date = "管理员修改后的计划", False, TODAY
        college.name, lab.location = "管理员修改后的学院", "真实实验楼 A101"
        ee = await session.scalar(select(College).where(College.code == "EE"))
        ee.status = 0
        device_id, plan_id, college_id, lab_id = device.id, plan.id, college.id, lab.id
        await session.commit()
    before = await counts(session_factory)
    await seed_initial_catalog(engine, today=TODAY + timedelta(days=100))
    assert await counts(session_factory) == before
    async with session_factory() as session:
        device = await session.get(Device, device_id)
        plan = await session.get(DeviceMaintenancePlan, plan_id)
        assert device.name == "管理员修改后的设备" and device.status == "MAINTENANCE"
        assert plan.title == "管理员修改后的计划" and not plan.active and plan.due_date == TODAY
        assert (await session.get(College, college_id)).name == "管理员修改后的学院"
        assert (await session.get(Lab, lab_id)).location == "真实实验楼 A101"


async def test_reuses_tenant_and_lab_and_does_not_touch_colliding_asset(session_factory):
    actor_id = await add_admin(session_factory)
    async with session_factory() as session:
        college = College(code="CSE", name="计算机学院", status=1, manager_id=actor_id)
        session.add(college)
        await session.flush()
        lab = Lab(name="真实实验室", college_id=college.id, manager_id=actor_id, status=1)
        session.add(lab)
        await session.flush()
        device = Device(
            college_id=college.id,
            lab_id=lab.id,
            name="已有资产",
            status="IDLE",
            asset_code="LF-INIT-CS-OSC",
            tags=["真实资产"],
        )
        session.add(device)
        await session.commit()
        college_id, lab_id, device_id = college.id, lab.id, device.id
    result = await seed_initial_catalog(session_factory.kw["bind"], today=TODAY)
    assert result["colleges"] == 2 and result["labs"] == 2
    assert result["devices"] == 17 and result["plans"] == 17
    async with session_factory() as session:
        assert await session.scalar(select(College.id).where(College.code == "CS")) is None
        devices = list(
            (await session.scalars(select(Device).where(Device.college_id == college_id))).all()
        )
        assert len(devices) == 6 and all(d.lab_id == lab_id for d in devices)
        assert (await session.get(Device, device_id)).name == "已有资产"
        assert (
            await session.scalar(
                select(DeviceMaintenancePlan.id).where(DeviceMaintenancePlan.device_id == device_id)
            )
            is None
        )


async def test_missing_administrator_fails_before_writing_catalog(session_factory):
    with pytest.raises(RuntimeError, match="enabled system administrator"):
        await seed_initial_catalog(session_factory.kw["bind"], today=TODAY)
    after = await counts(session_factory)
    assert not any(after.values())


async def test_partial_initialization_can_resume_without_creating_duplicate_assets(session_factory):
    await add_admin(session_factory)
    engine = session_factory.kw["bind"]
    await seed_initial_catalog(engine, today=TODAY)
    async with session_factory() as session:
        plan = await session.scalar(
            select(DeviceMaintenancePlan).order_by(DeviceMaintenancePlan.id)
        )
        device_id = plan.device_id
        await session.delete(plan)
        await session.commit()
    result = await seed_initial_catalog(engine, today=TODAY)
    assert result["devices"] == 0 and result["plans"] == 1
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Device)) == 18
        assert await session.scalar(select(func.count()).select_from(DevicePool)) == 18
        assert (
            await session.scalar(
                select(func.count())
                .select_from(DeviceMaintenancePlan)
                .where(DeviceMaintenancePlan.device_id == device_id)
            )
            == 1
        )
