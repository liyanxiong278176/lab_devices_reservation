from datetime import date

from app.infrastructure.db.base import Base
from app.infrastructure.db.models import College, Device, Lab, Reservation, ReservationItem, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def test_core_models_round_trip_with_sqlite() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        college = College(code="CSE", name="计算机学院")
        user = User(
            username="student-001",
            password_hash="not-a-real-password",
            real_name="测试用户",
            college=college,
        )
        lab = Lab(name="智能实验室", college=college, manager=user)
        device = Device(
            name="GPU 工作站",
            college=college,
            lab=lab,
            status="IDLE",
            need_approval=False,
        )
        reservation = Reservation(
            college_id=1,
            user=user,
            device=device,
            purpose="模型训练",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 2),
            status="APPROVED",
        )
        reservation.days.extend(
            [
                ReservationItem(device=device, reservation_date=date(2026, 9, 1)),
                ReservationItem(device=device, reservation_date=date(2026, 9, 2)),
            ]
        )
        session.add(reservation)
        await session.commit()

        saved = await session.scalar(select(Reservation).where(Reservation.id == reservation.id))

    await engine.dispose()

    assert saved is not None
    assert saved.start_date == date(2026, 9, 1)
    assert len(saved.days) == 2
