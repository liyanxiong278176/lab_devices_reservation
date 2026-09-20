"""Create and remove isolated data for the browser-level regression suite.

The fixture never touches the seeded demo users or the three real colleges. A
unique ``e2e-`` prefix makes accidental cleanup outside the test tenant
impossible to miss in review.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth.security import hash_password
from app.core.settings import Settings
from app.infrastructure.db.models import (
    College,
    Device,
    IdempotencyKey,
    Lab,
    Notification,
    OutboxTask,
    RepairReport,
    Reservation,
    ReservationItem,
    Role,
    User,
    user_roles,
)
from app.infrastructure.db.session import build_engine, build_session_factory
from sqlalchemy import delete, select


def validate_prefix(value: str) -> str:
    if not re.fullmatch(r"e2e-[a-z0-9-]{6,40}", value):
        raise ValueError("prefix must match e2e-[a-z0-9-]{6,40}")
    return value


async def seed(prefix: str) -> None:
    settings = Settings()
    engine = build_engine(settings)
    factory = build_session_factory(engine)
    password = "E2e-123456"
    username = f"{prefix}-user"
    device_name = f"{prefix}-device"
    manager_username = f"{prefix}-manager"
    try:
        async with factory() as session:
            student_role = await session.scalar(select(Role).where(Role.role_code == "STUDENT"))
            manager_role = await session.scalar(select(Role).where(Role.role_code == "LAB_ADMIN"))
            if student_role is None or manager_role is None:
                raise RuntimeError("required STUDENT/LAB_ADMIN roles are missing")

            college = College(
                code=prefix.upper(),
                name=f"E2E 测试学院 {prefix}",
                status=1,
            )
            manager = User(
                username=manager_username,
                password_hash=hash_password(password),
                real_name="E2E 负责人",
                user_type="STAFF",
                status=1,
                roles=[manager_role],
            )
            student = User(
                username=username,
                password_hash=hash_password(password),
                real_name="E2E 普通用户",
                user_type="STUDENT",
                status=1,
                roles=[student_role],
            )
            college.users.extend([manager, student])
            lab = Lab(
                name=f"{prefix}-lab",
                location="E2E 测试楼",
                description="浏览器回归测试专用实验室",
                status=1,
                manager=manager,
            )
            college.labs.append(lab)
            device = Device(
                name=device_name,
                brand="E2E",
                model=device_name,
                specs="E2E regression fixture",
                status="IDLE",
                need_approval=True,
                max_reservation_days=8,
                description="浏览器回归测试专用设备",
                college=college,
                lab=lab,
            )
            session.add_all([college, manager, student, lab, device])
            await session.flush()
            college.manager_id = manager.id
            await session.commit()
            print(
                json.dumps(
                    {
                        "prefix": prefix,
                        "username": username,
                        "password": password,
                        "manager_username": manager_username,
                        "device_id": device.id,
                        "device_name": device_name,
                        "college_id": college.id,
                        "created_at": datetime.now(UTC).isoformat(),
                    },
                    ensure_ascii=False,
                )
            )
    finally:
        await engine.dispose()


async def cleanup(prefix: str) -> None:
    settings = Settings()
    engine = build_engine(settings)
    factory = build_session_factory(engine)
    try:
        async with factory() as session:
            college = await session.scalar(select(College).where(College.code == prefix.upper()))
            if college is None:
                return
            users = list(
                (
                    await session.scalars(
                        select(User).where(User.username.like(f"{prefix}%"))
                    )
                ).all()
            )
            user_ids = [user.id for user in users]
            device_ids = list(
                (
                    await session.scalars(select(Device.id).where(Device.college_id == college.id))
                ).all()
            )
            reservation_ids = list(
                (
                    await session.scalars(
                        select(Reservation.id).where(Reservation.college_id == college.id)
                    )
                ).all()
            )
            if reservation_ids:
                await session.execute(
                    delete(ReservationItem).where(ReservationItem.reservation_id.in_(reservation_ids))
                )
            if device_ids:
                await session.execute(
                    delete(RepairReport).where(RepairReport.device_id.in_(device_ids))
                )
                await session.execute(
                    delete(Reservation).where(Reservation.id.in_(reservation_ids))
                )
            await session.execute(delete(Notification).where(Notification.college_id == college.id))
            await session.execute(delete(OutboxTask).where(OutboxTask.college_id == college.id))
            if user_ids:
                await session.execute(
                    delete(IdempotencyKey).where(IdempotencyKey.user_id.in_(user_ids))
                )
            await session.execute(delete(Device).where(Device.college_id == college.id))
            await session.execute(delete(Lab).where(Lab.college_id == college.id))
            if user_ids:
                await session.execute(
                    College.__table__.update()
                    .where(College.id == college.id)
                    .values(manager_id=None)
                )
                await session.execute(delete(user_roles).where(user_roles.c.user_id.in_(user_ids)))
                await session.execute(delete(User).where(User.id.in_(user_ids)))
            await session.execute(delete(College).where(College.id == college.id))
            await session.commit()
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("seed", "cleanup"))
    parser.add_argument("--prefix", required=True, type=validate_prefix)
    args = parser.parse_args()
    asyncio.run(seed(args.prefix) if args.action == "seed" else cleanup(args.prefix))


if __name__ == "__main__":
    main()
