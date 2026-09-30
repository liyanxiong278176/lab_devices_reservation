import pytest
from app.infrastructure.db.base import Base
from app.infrastructure.db.models import (
    AuthorizationVersion,
    College,
    Device,
    Lab,
    Permission,
    Role,
    User,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


@pytest.fixture
async def session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with factory() as session:
        session.add(AuthorizationVersion(id=1, version=1))
        await session.commit()
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
async def seeded(session_factory: async_sessionmaker[AsyncSession]):
    async with session_factory() as session:
        c1 = College(code="CSE", name="计算机学院")
        c2 = College(code="BIO", name="生命学院")
        all_codes = (
            "dashboard:read",
            "device:read",
            "device:manage",
            "device:documents:manage",
            "reservation:create",
            "reservation:read:own",
            "reservation:read:scope",
            "reservation:cancel",
            "reservation:check-in",
            "reservation:return",
            "reservation:approve",
            "reservation:handover",
            "reservation:accept-return",
            "notification:read:own",
            "repair:create",
            "repair:read:own",
            "repair:read:scope",
            "repair:handle",
            "repair:confirm",
            "report:read",
            "reservation-rule:manage",
            "maintenance:manage",
            "feedback:create",
            "feedback:read:own",
            "feedback:read:scope",
            "organization:read",
            "organization:manage",
            "user:manage",
            "rbac:manage",
            "ai:use",
            "ai:knowledge:manage",
            "ai:usage:read:scope",
        )
        permission_map = {
            code: Permission(
                permission_code=code,
                permission_name=code,
                module=code.split(":", 1)[0],
            )
            for code in all_codes
        }
        student_codes = {
            "dashboard:read",
            "device:read",
            "reservation:create",
            "reservation:read:own",
            "reservation:cancel",
            "reservation:check-in",
            "reservation:return",
            "notification:read:own",
            "repair:create",
            "repair:read:own",
            "repair:confirm",
            "feedback:create",
            "feedback:read:own",
            "ai:use",
        }
        manager_codes = {
            "dashboard:read",
            "device:read",
            "device:manage",
            "device:documents:manage",
            "reservation:read:scope",
            "reservation:approve",
            "reservation:handover",
            "reservation:accept-return",
            "notification:read:own",
            "repair:read:scope",
            "repair:handle",
            "report:read",
            "reservation-rule:manage",
            "maintenance:manage",
            "feedback:read:scope",
            "organization:read",
            "ai:use",
            "ai:knowledge:manage",
            "ai:usage:read:scope",
        }
        student_role = Role(
            role_code="STUDENT",
            role_name="学生",
            is_system=True,
            permissions=[permission_map[code] for code in student_codes],
        )
        manager_role = Role(
            role_code="LAB_ADMIN",
            role_name="实验室负责人",
            is_system=True,
            permissions=[permission_map[code] for code in manager_codes],
        )
        admin_role = Role(
            role_code="SYS_ADMIN",
            role_name="系统管理员",
            is_system=True,
            permissions=list(permission_map.values()),
        )
        student1 = User(
            username="student-1",
            password_hash="test",
            real_name="学生一",
            college=c1,
            roles=[student_role],
            status=1,
        )
        student2 = User(
            username="student-2",
            password_hash="test",
            real_name="学生二",
            college=c2,
            roles=[student_role],
            status=1,
        )
        manager = User(
            username="manager-1",
            password_hash="test",
            real_name="负责人",
            college=c1,
            status=1,
        )
        manager.roles.append(manager_role)
        lab = Lab(name="智能实验室", college=c1, manager=manager, status=1)
        device = Device(
            name="GPU 工作站",
            college=c1,
            lab=lab,
            status="IDLE",
            need_approval=False,
            max_reservation_days=8,
        )
        other_device = Device(
            name="生物显微镜",
            college=c2,
            status="IDLE",
            need_approval=False,
        )
        session.add_all(
            [
                c1,
                c2,
                student1,
                student2,
                manager,
                lab,
                device,
                other_device,
                student_role,
                manager_role,
                admin_role,
                *permission_map.values(),
            ]
        )
        await session.commit()
        return session_factory, c1, c2, student1, student2, manager, device, other_device
