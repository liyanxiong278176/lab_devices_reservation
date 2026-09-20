import pytest
from app.infrastructure.db.base import Base
from app.infrastructure.db.models import College, Device, Lab, Role, User
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
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
async def seeded(session_factory: async_sessionmaker[AsyncSession]):
    async with session_factory() as session:
        c1 = College(code="CSE", name="计算机学院")
        c2 = College(code="BIO", name="生命学院")
        student1 = User(
            username="student-1",
            password_hash="test",
            real_name="学生一",
            college=c1,
            status=1,
        )
        student2 = User(
            username="student-2",
            password_hash="test",
            real_name="学生二",
            college=c2,
            status=1,
        )
        manager = User(
            username="manager-1",
            password_hash="test",
            real_name="负责人",
            college=c1,
            status=1,
        )
        role = Role(role_code="LAB_ADMIN", role_name="实验室负责人")
        manager.roles.append(role)
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
        session.add_all([c1, c2, student1, student2, manager, lab, device, other_device])
        await session.commit()
        return session_factory, c1, c2, student1, student2, manager, device, other_device
