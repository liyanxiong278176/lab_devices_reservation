"""Seed repeatable local demo accounts, colleges, labs, and devices.

This script is intentionally unavailable in production. Passwords are read
from the invoking process environment and are never stored in source control.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth.security import hash_password
from app.core.settings import Settings
from app.infrastructure.db.bootstrap import ensure_bootstrap_admin
from app.infrastructure.db.models import (
    College,
    Device,
    DeviceCategory,
    DeviceStatusHistory,
    Lab,
    Role,
    User,
)
from app.infrastructure.db.operational_bootstrap import ensure_operational_metadata
from app.infrastructure.db.session import build_engine, build_session_factory
from sqlalchemy import select

DEMO_STRUCTURE = (
    {
        "code": "CS",
        "college": "计算机学院",
        "manager_username": "manager_cs",
        "manager_name": "计算机学院实验室负责人",
        "lab": "计算机基础实验室",
        "location": "计算中心 A301",
        "devices": (
            (
                "CS-INS-001",
                "数字示波器（计算机学院）",
                "电子测量",
                "Rigol",
                "DS1104Z",
                ["示波器探头", "电源线"],
            ),
            (
                "CS-INS-002",
                "光学显微镜（计算机学院）",
                "显微成像",
                "Olympus",
                "CX23",
                ["目镜", "载物台夹"],
            ),
        ),
    },
    {
        "code": "EE",
        "college": "电气学院",
        "manager_username": "manager_ee",
        "manager_name": "电气学院实验室负责人",
        "lab": "电气工程实验室",
        "location": "电气楼 B205",
        "devices": (
            (
                "EE-INS-001",
                "电力电子实验平台（电气学院）",
                "电子测量",
                "Keysight",
                "EDU-PWR-01",
                ["测试线", "安全护罩"],
            ),
            (
                "EE-INS-002",
                "绝缘电阻测试仪（电气学院）",
                "电子测量",
                "Fluke",
                "1508",
                ["测试线", "探针"],
            ),
        ),
    },
    {
        "code": "EIE",
        "college": "电子信息学院",
        "manager_username": "manager_eie",
        "manager_name": "电子信息学院实验室负责人",
        "lab": "通信与信号实验室",
        "location": "信息楼 C412",
        "devices": (
            (
                "EIE-INS-001",
                "频谱分析仪（电子信息学院）",
                "光谱分析",
                "Keysight",
                "N9320B",
                ["射频线缆", "电源线"],
            ),
            (
                "EIE-INS-002",
                "信号发生器（电子信息学院）",
                "电子测量",
                "Rigol",
                "DG1022Z",
                ["BNC 线", "电源线"],
            ),
        ),
    },
)


async def seed() -> None:
    settings = Settings()
    if settings.environment == "prod":
        raise RuntimeError("demo seed data must never be applied to production")
    admin_password = settings.bootstrap_admin_password
    student_password = os.environ.get("LAB_DEMO_USER_PASSWORD")
    manager_password = os.environ.get("LAB_DEMO_MANAGER_PASSWORD")
    if not admin_password:
        raise RuntimeError("set LAB_BOOTSTRAP_ADMIN_PASSWORD before seeding the local admin")
    if not student_password or not manager_password:
        raise RuntimeError(
            "set LAB_DEMO_USER_PASSWORD and LAB_DEMO_MANAGER_PASSWORD before seeding"
        )

    engine = build_engine(settings)
    factory = build_session_factory(engine)
    try:
        await ensure_bootstrap_admin(factory, settings)
        async with factory() as session:
            roles = {
                role.role_code: role
                for role in (
                    await session.scalars(
                        select(Role).where(
                            Role.role_code.in_(("STUDENT", "LAB_ADMIN", "SYS_ADMIN"))
                        )
                    )
                ).all()
            }
            if set(roles) != {"STUDENT", "LAB_ADMIN", "SYS_ADMIN"}:
                raise RuntimeError("required roles are missing; run Alembic migrations first")

            admin = await session.scalar(
                select(User).where(User.username == settings.bootstrap_admin_username)
            )
            if admin is None:
                raise RuntimeError("bootstrap admin was not created")

            async def get_or_create_user(
                *,
                username: str,
                real_name: str,
                role: Role,
                college: College,
                password: str,
            ) -> User:
                user = await session.scalar(select(User).where(User.username == username))
                if user is None:
                    user = User(
                        username=username,
                        password_hash=hash_password(password),
                        real_name=real_name,
                        user_type="STUDENT" if role.role_code == "STUDENT" else "STAFF",
                        college=college,
                        status=1,
                        roles=[role],
                    )
                    session.add(user)
                    await session.flush()
                return user

            seeded_devices = 0
            seeded_labs = 0
            for group in DEMO_STRUCTURE:
                college = await session.scalar(select(College).where(College.code == group["code"]))
                if college is None:
                    college = College(
                        code=group["code"],
                        name=group["college"],
                        status=1,
                    )
                    session.add(college)
                    await session.flush()

                manager = await get_or_create_user(
                    username=group["manager_username"],
                    real_name=group["manager_name"],
                    role=roles["LAB_ADMIN"],
                    college=college,
                    password=manager_password,
                )
                if college.manager_id is None:
                    college.manager_id = manager.id

                lab = await session.scalar(
                    select(Lab).where(
                        Lab.college_id == college.id,
                        Lab.name == group["lab"],
                    )
                )
                if lab is None:
                    lab = Lab(
                        college_id=college.id,
                        name=group["lab"],
                        location=group["location"],
                        manager_id=manager.id,
                        description=f"{group['college']}演示实验室",
                        status=1,
                    )
                    session.add(lab)
                    await session.flush()
                    seeded_labs += 1

                for asset_code, name, category_name, brand, model, accessories in group["devices"]:
                    existing = await session.scalar(
                        select(Device.id).where(Device.asset_code == asset_code)
                    )
                    if existing is not None:
                        continue
                    category = await session.scalar(
                        select(DeviceCategory).where(DeviceCategory.name == category_name)
                    )
                    if category is None:
                        raise RuntimeError(f"device category {category_name!r} is missing")
                    device = Device(
                        college_id=college.id,
                        lab_id=lab.id,
                        category_id=category.id,
                        name=name,
                        brand=brand,
                        model=model,
                        specs="本地演示设备；铭牌、规格及配件以实验室现场资产为准。",
                        status="IDLE",
                        need_approval=True,
                        max_reservation_days=8,
                        description="用于本地演示预约、审批、设备交接、归还验收和报修链路。",
                        tags=[group["college"], "演示设备"],
                        accessory_checklist=accessories,
                        asset_code=asset_code,
                        serial_number=f"DEMO-{asset_code}",
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
                            reason="首次初始化本地演示设备",
                            operator_id=admin.id,
                        )
                    )
                    seeded_devices += 1

            cs_college = await session.scalar(select(College).where(College.code == "CS"))
            if cs_college is None:
                raise RuntimeError("computer-science college is missing")
            await get_or_create_user(
                username="zhangsan",
                real_name="张三",
                role=roles["STUDENT"],
                college=cs_college,
                password=student_password,
            )
            await session.commit()

        await ensure_operational_metadata(factory, settings)
        print(
            "本地演示数据已就绪：3 个学院、3 个实验室、"
            f"新增 {seeded_devices} 台设备，新增 {seeded_labs} 个实验室；"
            "管理员 admin、普通用户 zhangsan。"
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
