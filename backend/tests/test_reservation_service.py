from datetime import date, timedelta

import pytest
from app.api.v2.schemas import ReservationPlanRequest
from app.application.recommendations import RecommendationService
from app.application.reservations import ReservationService
from app.auth.security import Principal
from app.core.errors import ApiError
from app.infrastructure.db.models import OutboxTask, Reservation, User
from sqlalchemy import select


def principal(user: User, *roles: str) -> Principal:
    return Principal(
        user_id=user.id,
        username=user.username,
        college_id=user.college_id,
        roles=roles,
        token_type="access",
        token_id="test-token",
    )


@pytest.mark.asyncio
async def test_college_isolation_and_idempotent_reservation(seeded) -> None:
    factory, _, _, student1, student2, _, device, _ = seeded
    target = date.today() + timedelta(days=2)
    plan = ReservationPlanRequest(
        device_id=device.id,
        start_date=target,
        end_date=target + timedelta(days=1),
        purpose="模型训练",
    )

    async with factory() as session:
        service = ReservationService(session, principal(student1, "STUDENT"))
        first = await service.create(plan, idempotency_key="reservation-test-001")
        replay = await service.create(plan, idempotency_key="reservation-test-001")
        assert [row.id for row in first.created] == [row.id for row in replay.created]
        assert len(first.created[0].dates) == 2
        legacy_row = await session.scalar(
            select(Reservation).where(Reservation.id == first.created[0].id)
        )
        assert legacy_row is not None
        assert legacy_row.start_time is not None
        assert legacy_row.end_time is not None

    async with factory() as session:
        hidden = ReservationService(session, principal(student2, "STUDENT"))
        items, total = await hidden.list_devices()
        assert [item.name for item in items] == ["生物显微镜"]
        assert total == 1
        with pytest.raises(ApiError) as error:
            await hidden.preflight(plan)
        assert error.value.code == "DEVICE_NOT_FOUND"

    async with factory() as session:
        conflict = ReservationService(session, principal(student1, "STUDENT"))
        with pytest.raises(ApiError) as error:
            await conflict.create(
                ReservationPlanRequest(
                    device_id=device.id,
                    start_date=target,
                    end_date=target,
                    purpose="重复预约",
                )
            )
        assert error.value.code == "RESERVATION_CONFLICT"

    async with factory() as session:
        cancelled = await ReservationService(session, principal(student1, "STUDENT")).cancel(
            first.created[0].id
        )
        assert cancelled.status == "CANCELLED"
        reopened = await ReservationService(session, principal(student1, "STUDENT")).create(
            ReservationPlanRequest(
                device_id=device.id,
                start_date=target,
                end_date=target,
                purpose="释放后重新预约",
            )
        )
        assert reopened.created[0].status == "APPROVED"


@pytest.mark.asyncio
async def test_recommendations_follow_college_and_manager_scope(seeded) -> None:
    factory, _, _, student1, student2, manager, device, other_device = seeded
    async with factory() as session:
        student_items = await RecommendationService(
            session,
            principal(student1, "STUDENT"),
        ).recommend()
        other_student_items = await RecommendationService(
            session,
            principal(student2, "STUDENT"),
        ).recommend()
        manager_items = await RecommendationService(
            session,
            principal(manager, "LAB_ADMIN"),
        ).recommend()

    assert [item.device_id for item in student_items] == [device.id]
    assert [item.device_id for item in other_student_items] == [other_device.id]
    assert [item.device_id for item in manager_items] == [device.id]


@pytest.mark.asyncio
async def test_manager_approval_is_limited_to_owned_lab(seeded) -> None:
    factory, _, _, student1, _, manager, device, _ = seeded
    device.need_approval = True
    target = date.today() + timedelta(days=4)
    async with factory() as session:
        session.add(device)
        await session.commit()
        created = await ReservationService(
            session,
            principal(student1, "STUDENT"),
        ).create(
            ReservationPlanRequest(
                device_id=device.id,
                start_date=target,
                end_date=target,
                purpose="需要审批的实验",
            )
        )
        assert created.created[0].status == "PENDING"

    async with factory() as session:
        approved = await ReservationService(
            session,
            principal(manager, "LAB_ADMIN"),
        ).approve(created.created[0].id, True)
        assert approved.status == "APPROVED"
        pending = await ReservationService(
            session,
            principal(manager, "LAB_ADMIN"),
        ).pending_approvals()
        assert pending.total == 0

        approval_notification = await session.scalar(
            select(OutboxTask).where(
                OutboxTask.task_key == f"notification:reservation:{created.created[0].id}:approved"
            )
        )
        assert approval_notification is not None
        assert approval_notification.payload["title"] == "预约申请已通过"
