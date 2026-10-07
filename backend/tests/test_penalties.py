from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from app.api.v2.schemas import ReservationPlanRequest
from app.application.penalties import PenaltyService
from app.application.penalty_processing import ensure_overdue_started
from app.application.reservations import ReservationService
from app.auth.security import Principal
from app.core.business_time import business_day_end_utc_naive, business_day_start_utc_naive
from app.core.errors import ApiError
from app.core.settings import Settings
from app.infrastructure.db.models import (
    AuditLog,
    College,
    CollegeCreditAccount,
    OutboxTask,
    PenaltyAppeal,
    PenaltyCase,
    Reservation,
    ReservationBookingRestriction,
    User,
)
from app.infrastructure.tasks.worker import OutboxWorker
from fastapi import FastAPI
from sqlalchemy import func, select


def _principal(user: User, *roles: str, permissions: tuple[str, ...] = ()) -> Principal:
    return Principal(
        user_id=user.id,
        username=user.username,
        college_id=user.college_id,
        roles=roles,
        token_type="access",
        token_id=f"penalty-test-{user.id}",
        permissions=permissions,
    )


def _tiers(*, no_show_points: int = 15, no_show_block_days: int = 3):
    return {
        "NO_SHOW": [
            {"occurrence": 1, "points": no_show_points, "block_days": no_show_block_days}
        ],
        "OVERDUE_RETURN": [{"occurrence": 1, "points": 0, "block_days": 0}],
        "MANUAL_VIOLATION": [],
    }


@pytest.mark.asyncio
async def test_only_college_head_can_publish_audited_policy(seeded) -> None:
    factory, college, _, student, _, manager, _, _ = seeded
    async with factory() as session:
        stored_college = await session.get(College, college.id)
        assert stored_college is not None
        stored_college.manager_id = manager.id
        await session.commit()

        manager_service = PenaltyService(
            session,
            _principal(manager, "LAB_ADMIN"),
        )
        saved = await manager_service.save_policy(2, _tiers())
        assert saved["version"] == 1
        assert saved["grace_days"] == 2
        assert saved["tiers"]["NO_SHOW"][0]["points"] == 15

        audit_count = int(
            await session.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.college_id == college.id,
                    AuditLog.action == "PENALTY_POLICY_VERSION_CREATE",
                )
            )
            or 0
        )
        assert audit_count == 1

        stored_college.manager_id = student.id
        await session.commit()
        with pytest.raises(ApiError) as error:
            await manager_service.save_policy(2, _tiers(no_show_points=20))
        assert error.value.code == "FORBIDDEN"


@pytest.mark.asyncio
async def test_no_show_applies_college_rule_cancels_pending_bookings_and_revocation_releases_hold(
    seeded,
) -> None:
    factory, college, _, student, _, manager, device, _ = seeded
    college_id = college.id
    student_id = student.id
    device_id = device.id
    device_lab_id = device.lab_id
    async with factory() as session:
        stored_college = await session.get(College, college.id)
        assert stored_college is not None
        stored_college.manager_id = manager.id
        await session.commit()

        await PenaltyService(
            session,
            _principal(manager, "LAB_ADMIN"),
        ).save_policy(2, _tiers())

        student_principal = _principal(
            student,
            "STUDENT",
            permissions=("reservation:create", "device:read"),
        )
        today = date.today()
        missed = await ReservationService(session, student_principal).create(
            ReservationPlanRequest(
                device_id=device.id,
                start_date=today,
                end_date=today,
                purpose="处罚流程集成验证：爽约预约",
            )
        )
        future = await ReservationService(session, student_principal).create(
            ReservationPlanRequest(
                device_id=device.id,
                start_date=today + timedelta(days=4),
                end_date=today + timedelta(days=4),
                purpose="处罚流程集成验证：尚未开始的预约",
            )
        )
        missed_id = missed.created[0].id
        future_id = future.created[0].id
        await session.commit()

    app = FastAPI()
    app.state.settings = Settings(environment="test", enable_workers=False)
    app.state.session_factory = factory
    await OutboxWorker(app)._handle(
        "RESERVATION_NO_SHOW",
        {"reservation_id": missed_id, "user_id": student.id, "college_id": college.id},
        task_key=f"test:no-show:{missed_id}",
    )

    async with factory() as session:
        penalty = await session.scalar(
            select(PenaltyCase).where(
                PenaltyCase.reservation_id == missed_id,
                PenaltyCase.violation_type == "NO_SHOW",
            )
        )
        user = await session.get(User, student.id)
        account = await session.scalar(
            select(CollegeCreditAccount).where(
                CollegeCreditAccount.user_id == student.id,
                CollegeCreditAccount.college_id == college.id,
            )
        )
        restriction = await session.scalar(
            select(ReservationBookingRestriction).where(
                ReservationBookingRestriction.penalty_case_id == penalty.id
            )
        )
        penalty_id = penalty.id
        future_row = await session.get(Reservation, future_id)
        assert penalty is not None and penalty.points_delta == -15
        assert penalty.event_at == business_day_end_utc_naive(today)
        assert penalty.reservation_block_days == 3
        assert user is not None and user.credit_score == 85
        assert account is not None and account.points == 85
        assert restriction is not None
        assert restriction.scope_type == "LAB" and restriction.scope_id == device_lab_id
        assert future_row is not None and future_row.status == "CANCELLED"
        release_tasks = list(
            (
                await session.scalars(
                    select(OutboxTask).where(
                        OutboxTask.task_key.in_(
                            [
                                f"notification:penalty:{penalty_id}:reservation:{future_id}:cancelled",
                                f"reservation-quota:reconcile:penalty:{penalty_id}:{future_id}",
                            ]
                        )
                    )
                )
            ).all()
        )
        assert {task.task_type for task in release_tasks} == {
            "NOTIFICATION",
            "RESERVATION_QUOTA_RECONCILE",
        }
        assert all(
            task.execute_at <= datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=2)
            for task in release_tasks
        )

        with pytest.raises(ApiError) as blocked_booking:
            await ReservationService(session, student_principal).create(
                ReservationPlanRequest(
                    device_id=device_id,
                    start_date=today + timedelta(days=2),
                    end_date=today + timedelta(days=2),
                    purpose="处罚期间不能绕过限制直接提交预约",
                )
            )
        assert blocked_booking.value.code == "BOOKING_RESTRICTED"

        appeal = await PenaltyService(
            session,
            student_principal,
        ).submit_appeal(
            penalty_id,
            reason="已按时到场，请复核交接记录。",
            evidence=None,
        )
        assert appeal["attempt_number"] == 1
        appeal_id = appeal["id"]

    async with factory() as session:
        result = await PenaltyService(
            session,
            _principal(manager, "LAB_ADMIN"),
        ).review_appeal(
            appeal_id,
            result="REVOKE",
            result_reason="核验实验室交接记录后确认系统记录有误。",
            points_deduction=None,
            block_days=None,
        )
        assert result["status"] == "REVIEWED"

    async with factory() as session:
        penalty = await session.scalar(
            select(PenaltyCase).where(PenaltyCase.reservation_id == missed_id)
        )
        appeal = await session.get(PenaltyAppeal, appeal_id)
        user = await session.get(User, student_id)
        account = await session.scalar(
            select(CollegeCreditAccount).where(
                CollegeCreditAccount.user_id == student_id,
                CollegeCreditAccount.college_id == college_id,
            )
        )
        restriction = await session.scalar(
            select(ReservationBookingRestriction).where(
                ReservationBookingRestriction.penalty_case_id == penalty_id
            )
        )
        assert penalty is not None and penalty.status == "REVOKED"
        assert appeal is not None and appeal.result == "REVOKE"
        assert user is not None and user.credit_score == 100
        assert account is not None and account.points == 100
        assert restriction is not None and restriction.released_at is not None

        rebooked = await ReservationService(
            session,
            student_principal,
        ).create(
            ReservationPlanRequest(
                device_id=device_id,
                start_date=date.today() + timedelta(days=5),
                end_date=date.today() + timedelta(days=5),
                purpose="处罚撤销后重新预约",
            )
        )
        assert rebooked.created


@pytest.mark.asyncio
async def test_overdue_starts_at_shanghai_midnight_after_reservation_end(seeded) -> None:
    factory, college, _, student, _, _, device, _ = seeded
    end_date = date.today() - timedelta(days=1)
    expected_start = business_day_start_utc_naive(date.today())

    async with factory() as session:
        reservation = Reservation(
            college_id=college.id,
            user_id=student.id,
            device_id=device.id,
            start_date=end_date,
            end_date=end_date,
            status="IN_USE",
            handover_status="PENDING",
        )
        session.add(reservation)
        await session.flush()

        overdue = await ensure_overdue_started(
            session,
            reservation,
            now=expected_start,
        )

        assert overdue is not None
        assert overdue.started_at == expected_start
