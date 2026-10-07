"""Add explicitly labelled starter inventory without replacing operator data."""

from __future__ import annotations

from datetime import date

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api.v2.schemas import MaintenancePlanWrite
from app.application.lifecycle import append_audit
from app.application.maintenance import MaintenanceService, add_interval
from app.auth.security import Principal
from app.infrastructure.db.models import (
    College,
    Device,
    DeviceCategory,
    DeviceMaintenancePlan,
    DevicePool,
    DeviceStatusHistory,
    Lab,
    Role,
    User,
)
from app.infrastructure.db.session import build_session_factory

COLLEGES = (("CS", "计算机学院"), ("EE", "电气学院"), ("EIE", "电子信息学院"))
SEED_TAG = "初始化示例"
SEED_LOCK = "labflow:initial-catalog:v1"
# Asset suffix, display name, category, checklist, plan type, interval, unit.
DEVICES = (
    ("OSC", "数字示波器", "电子测量", ("示波器探头", "电源线"), "ROUTINE", 30, "DAY"),
    ("MIC", "光学显微镜", "显微成像", ("目镜", "载物台夹"), "ROUTINE", 30, "DAY"),
    ("SPEC", "频谱分析仪", "光谱分析", ("射频线缆", "电源线"), "CALIBRATION", 6, "MONTH"),
    ("BAL", "电子天平", "称量设备", ("称量盘", "校准砝码"), "CALIBRATION", 6, "MONTH"),
    ("GEN", "信号发生器", "电子测量", ("BNC 线", "电源线"), "SAFETY_CHECK", 1, "YEAR"),
    ("INC", "恒温培养箱", "环境试验", ("托盘", "电源线"), "SAFETY_CHECK", 1, "YEAR"),
)
PLAN_LABELS = {"ROUTINE": "周期保养", "CALIBRATION": "仪器校准", "SAFETY_CHECK": "安全检查"}


async def seed_initial_catalog(
    engine: AsyncEngine,
    *,
    admin_username: str = "admin",
    today: date | None = None,
) -> dict[str, int]:
    """Serialize deployment seeds on MySQL, including across separate deploy processes."""
    factory = build_session_factory(engine)
    if engine.dialect.name != "mysql":
        return await _seed(factory, admin_username, today or date.today())
    # MaintenanceService commits per device; a separate connection keeps the
    # named lock held across those commits, and disconnect releases it on a crash.
    async with engine.connect() as connection:
        acquired = await connection.scalar(text("SELECT GET_LOCK(:name, 60)"), {"name": SEED_LOCK})
        if acquired != 1:
            raise RuntimeError("another catalog initialization is running; retry deployment")
        try:
            return await _seed(factory, admin_username, today or date.today())
        finally:
            await connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": SEED_LOCK})


async def _seed(
    factory: async_sessionmaker[AsyncSession], admin_username: str, today: date
) -> dict[str, int]:
    counts = dict(colleges=0, labs=0, categories=0, devices=0, plans=0, skipped_devices=0)
    async with factory() as session:
        actor = await session.scalar(
            select(User)
            .join(User.roles)
            .where(User.status == 1, Role.role_code == "SYS_ADMIN")
            .order_by((User.username == admin_username).desc(), User.id)
            .limit(1)
        )
        if actor is None:
            raise RuntimeError(
                "catalog initialization requires an enabled system administrator; "
                "configure LAB_BOOTSTRAP_ADMIN_PASSWORD for a fresh installation"
            )
        principal = Principal(
            user_id=actor.id,
            username=actor.username,
            college_id=actor.college_id,
            roles=("SYS_ADMIN",),
            token_type="access",
            token_id="deployment-catalog-initialization",
        )
        for code, college_name in COLLEGES:
            # Reuse a matching name when an installation uses a different college code.
            college = await session.scalar(
                select(College)
                .where(or_(College.code == code, College.name == college_name))
                .order_by((College.code == code).desc(), College.id)
                .limit(1)
            )
            if college is None:
                college = College(code=code, name=college_name, status=1)
                session.add(college)
                await session.flush()
                counts["colleges"] += 1
            if college.status != 1:
                continue
            lab = await session.scalar(
                select(Lab)
                .where(Lab.college_id == college.id, Lab.status == 1)
                .order_by(Lab.id)
                .limit(1)
            )
            if lab is None:
                lab = Lab(
                    college_id=college.id,
                    name=f"{college.name}共享设备示例实验室",
                    location="示例位置，请由管理员填写实际位置",
                    manager_id=college.manager_id or actor.id,
                    description="部署初始化的示例实验室，可由管理员维护。",
                    status=1,
                )
                session.add(lab)
                await session.flush()
                counts["labs"] += 1
            for suffix, name, category_name, accessories, kind, interval, unit in DEVICES:
                asset_code = f"LF-INIT-{code}-{suffix}"
                device = await session.scalar(select(Device).where(Device.asset_code == asset_code))
                if device is not None:
                    counts["skipped_devices"] += 1
                    # Preserve retired/deleted/transferred assets and manually reused codes.
                    if (
                        device.college_id != college.id
                        or device.status != "IDLE"
                        or SEED_TAG not in (device.tags or [])
                    ):
                        continue
                else:
                    category = await session.scalar(
                        select(DeviceCategory)
                        .where(DeviceCategory.name == category_name)
                        .order_by(DeviceCategory.id)
                        .limit(1)
                    )
                    if category is None:
                        category = DeviceCategory(name=category_name, parent_id=0, sort=0)
                        session.add(category)
                        await session.flush()
                        counts["categories"] += 1
                    pool = DevicePool(name=f"示例{name}", college_id=college.id, lab_id=lab.id)
                    session.add(pool)
                    await session.flush()
                    device = Device(
                        pool_id=pool.id,
                        college_id=college.id,
                        lab_id=lab.id,
                        category_id=category.id,
                        name=f"示例{name}（{college.name}）",
                        brand="示例品牌",
                        model=f"STARTER-{suffix}",
                        specs="初始化示例数据，实际型号、精度与参数请由管理员核实后填写。",
                        status="IDLE",
                        need_approval=True,
                        max_reservation_days=8,
                        description="用于体验预约、审批、交接、归还和设备维护流程；不代表真实资产。",
                        tags=[SEED_TAG, college.name],
                        accessory_checklist=list(accessories),
                        asset_code=asset_code,
                        allow_external_loan=False,
                        risk_level="STANDARD",
                        requires_safety_ack=False,
                        requires_qualification=False,
                    )
                    session.add(device)
                    await session.flush()
                    session.add(
                        DeviceStatusHistory(
                            device_id=device.id,
                            college_id=college.id,
                            old_status=None,
                            new_status="IDLE",
                            reason="部署初始化示例设备，不代表真实资产验收",
                            operator_id=actor.id,
                        )
                    )
                    append_audit(
                        session,
                        user_id=actor.id,
                        college_id=college.id,
                        action="DEVICE_CREATE",
                        target_type="DEVICE",
                        target_id=device.id,
                        detail={"source": "deployment-catalog-v1", "asset_code": asset_code},
                    )
                    counts["devices"] += 1
                # Any existing plan counts as operator-managed, even if renamed or disabled.
                existing_plan = await session.scalar(
                    select(DeviceMaintenancePlan.id)
                    .where(DeviceMaintenancePlan.device_id == device.id)
                    .limit(1)
                )
                if existing_plan is None:
                    await MaintenanceService(session, principal).create_plan(
                        device.id,
                        MaintenancePlanWrite(
                            plan_type=kind,
                            title=f"示例{name} · {PLAN_LABELS[kind]}",
                            interval_value=interval,
                            interval_unit=unit,
                            due_date=add_interval(today, interval, unit),
                            active=True,
                        ),
                    )
                    counts["plans"] += 1
            await session.commit()
    return counts
