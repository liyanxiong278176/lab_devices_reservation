"""Shared violation, credit, reservation-hold, and overdue lifecycle rules."""

from __future__ import annotations

from calendar import monthrange
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.application.lifecycle import append_audit
from app.core.business_time import business_date_at_utc_naive, business_day_start_utc_naive
from app.core.errors import ApiError
from app.domain.reservation import RESERVATION_TRANSITIONS
from app.infrastructure.db.models import (
    CollegeCreditAccount,
    CreditEvent,
    Device,
    DeviceHandover,
    Lab,
    OutboxTask,
    PenaltyCase,
    PenaltyRuleVersion,
    Reservation,
    ReservationBookingRestriction,
    ReservationItem,
    ReservationOverdue,
    User,
)


def utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _subtract_three_months(value: datetime) -> datetime:
    month_index = value.year * 12 + value.month - 1 - 3
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    day = min(value.day, monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def enqueue_notification(
    session: AsyncSession,
    *,
    task_key: str,
    user_id: int,
    college_id: int | None,
    title: str,
    content: str,
    related_id: int | None,
    related_type: str,
    notification_type: str = "PENALTY_UPDATE",
    execute_at: datetime | None = None,
) -> None:
    now = execute_at or utcnow_naive()
    session.add(
        OutboxTask(
            task_key=task_key,
            task_type="NOTIFICATION",
            aggregate_key=f"notification:{task_key}",
            college_id=college_id,
            payload={
                "user_id": user_id,
                "college_id": college_id,
                "type": notification_type,
                "title": title,
                "content": content,
                "related_id": related_id,
                "related_type": related_type,
            },
            execute_at=now,
        )
    )


async def rule_version_at(
    session: AsyncSession,
    college_id: int,
    event_at: datetime,
) -> PenaltyRuleVersion | None:
    return await session.scalar(
        select(PenaltyRuleVersion)
        .where(
            PenaltyRuleVersion.college_id == college_id,
            PenaltyRuleVersion.effective_at <= event_at,
        )
        .order_by(PenaltyRuleVersion.effective_at.desc(), PenaltyRuleVersion.version.desc())
        .limit(1)
    )


async def _credit_delta(
    session: AsyncSession,
    *,
    user: User,
    college_id: int,
    reservation_id: int,
    delta: int,
    reason: str,
    operator_id: int | None,
    event_type: str,
    created_at: datetime,
    record_zero: bool = False,
) -> int:
    account = await session.scalar(
        select(CollegeCreditAccount)
        .where(
            CollegeCreditAccount.user_id == user.id,
            CollegeCreditAccount.college_id == college_id,
        )
        .with_for_update()
    )
    if account is None:
        starting_points = int(user.credit_score) if user.college_id == college_id else 100
        account = CollegeCreditAccount(
            user_id=user.id,
            college_id=college_id,
            points=starting_points,
        )
        session.add(account)
        await session.flush()
    old_points = int(account.points)
    account.points = max(0, min(100, old_points + delta))
    actual_delta = account.points - old_points
    if user.college_id == college_id:
        user.credit_score = account.points
    if actual_delta or record_zero:
        session.add(
            CreditEvent(
                user_id=user.id,
                college_id=college_id,
                reservation_id=reservation_id,
                event_type=event_type[:40],
                points=actual_delta,
                reason=reason[:500],
                operator_id=operator_id,
                created_at=created_at,
            )
        )
    return actual_delta


async def _cancel_other_reservations(
    session: AsyncSession,
    *,
    penalty: PenaltyCase,
    event_at: datetime,
) -> list[int]:
    if penalty.lab_id is None:
        return []
    processed_at = utcnow_naive()
    rows = list(
        (
            await session.scalars(
                select(Reservation)
                .join(Device, Device.id == Reservation.device_id)
                .options(
                    selectinload(Reservation.device),
                    selectinload(Reservation.days),
                    selectinload(Reservation.handover),
                )
                .where(
                    Reservation.id != penalty.reservation_id,
                    Reservation.user_id == penalty.user_id,
                    Reservation.college_id == penalty.college_id,
                    Device.lab_id == penalty.lab_id,
                    # A reservation whose first day is today is still unstarted
                    # while its status is APPROVED, so it is inside the suspension
                    # scope as well.
                    Reservation.start_date >= business_date_at_utc_naive(event_at),
                    Reservation.status.in_(("PENDING", "APPROVED")),
                )
                .order_by(Reservation.id)
                .with_for_update()
            )
        ).all()
    )
    affected_ids: list[int] = []
    for reservation in rows:
        old_status = reservation.status
        new_status = "REJECTED" if old_status == "PENDING" else "CANCELLED"
        if new_status not in RESERVATION_TRANSITIONS.get(old_status, ()):
            continue
        action = "驳回" if new_status == "REJECTED" else "取消"
        reason = (
            f"因预约 #{penalty.reservation_id} 的{penalty.violation_type}处罚，"
            f"系统自动{action}本预约。"
        )
        result = await session.execute(
            update(Reservation)
            .where(Reservation.id == reservation.id, Reservation.status == old_status)
            .values(
                status=new_status,
                reject_reason=reason,
                handover_status="CANCELLED",
                updated_at=processed_at,
            )
        )
        if result.rowcount != 1:
            continue
        reservation.status = new_status
        reservation.handover_status = "CANCELLED"
        if reservation.handover is not None:
            reservation.handover.status = "CANCELLED"
            reservation.handover.updated_at = processed_at
        dates = [item.reservation_date for item in reservation.days]
        await session.execute(
            delete(ReservationItem).where(ReservationItem.reservation_id == reservation.id)
        )
        affected_ids.append(reservation.id)
        append_audit(
            session,
            user_id=None,
            college_id=penalty.college_id,
            action="PENALTY_RESERVATION_REVOKE",
            target_type="RESERVATION",
            target_id=reservation.id,
            detail={
                "penalty_case_id": penalty.id,
                "previous_status": old_status,
                "new_status": new_status,
                "reason": reason,
            },
        )
        enqueue_notification(
            session,
            task_key=f"notification:penalty:{penalty.id}:reservation:{reservation.id}:cancelled",
            user_id=reservation.user_id,
            college_id=penalty.college_id,
            title="预约因违规处罚已处理",
            content=(
                f"预约 #{reservation.id} 尚未开始，因预约 #{penalty.reservation_id} 的违规处罚"
                f"已由系统{('驳回' if new_status == 'REJECTED' else '取消')}。"
                "如仍需使用，请重新预约。"
            ),
            related_id=reservation.id,
            related_type="RESERVATION",
            notification_type="RESERVATION_UPDATE",
            execute_at=processed_at,
        )
        if reservation.device is not None and dates:
            pool_id = int(reservation.device.pool_id or reservation.device_id)
            session.add(
                OutboxTask(
                    task_key=f"reservation-quota:reconcile:penalty:{penalty.id}:{reservation.id}",
                    task_type="RESERVATION_QUOTA_RECONCILE",
                    aggregate_key=f"reservation-quota:{pool_id}",
                    college_id=penalty.college_id,
                    payload={"pool_id": pool_id, "dates": [day.isoformat() for day in dates]},
                    execute_at=processed_at,
                )
            )
            for reserved_date in dates:
                session.add(
                    OutboxTask(
                        task_key=(
                            f"waitlist:promote:{reservation.device_id}:"
                            f"{reserved_date.isoformat()}:{reservation.id}"
                        ),
                        task_type="WAITLIST_PROMOTE",
                        aggregate_key=(
                            f"waitlist:{reservation.device_id}:{reserved_date.isoformat()}"
                        ),
                        college_id=penalty.college_id,
                        payload={
                            "device_id": reservation.device_id,
                            "reservation_date": reserved_date.isoformat(),
                        },
                        execute_at=processed_at,
                    )
                )
    return affected_ids


async def apply_violation_penalty(
    session: AsyncSession,
    reservation: Reservation,
    *,
    violation_type: str,
    event_at: datetime,
    reason: str,
    confirmed_by: int | None = None,
    rule_version_id: int | None = None,
) -> PenaltyCase | None:
    """Create one idempotent penalty snapshot and apply its side effects."""
    if reservation.college_id is None:
        return None
    existing = await session.scalar(
        select(PenaltyCase)
        .where(
            PenaltyCase.reservation_id == reservation.id,
            PenaltyCase.violation_type == violation_type,
        )
        .with_for_update()
    )
    if existing is not None:
        return existing

    version = (
        await session.get(PenaltyRuleVersion, rule_version_id)
        if rule_version_id is not None
        else await rule_version_at(session, reservation.college_id, event_at)
    )
    user = await session.scalar(
        select(User).where(User.id == reservation.user_id).with_for_update()
    )
    cutoff = _subtract_three_months(event_at)
    prior_case_ids = list(
        (
            await session.scalars(
                select(PenaltyCase.id)
                .where(
                    PenaltyCase.user_id == reservation.user_id,
                    PenaltyCase.college_id == reservation.college_id,
                    PenaltyCase.violation_type == violation_type,
                    PenaltyCase.status != "REVOKED",
                    PenaltyCase.event_at >= cutoff,
                    PenaltyCase.event_at <= event_at,
                )
                .with_for_update()
            )
        ).all()
    )
    previous_count = len(prior_case_ids)
    occurrence_number = previous_count + 1
    matching_tier: dict[str, Any] | None = None
    if version is not None:
        candidate_tiers = (version.tiers or {}).get(violation_type, [])
        valid_tiers = [
            tier
            for tier in candidate_tiers
            if isinstance(tier, dict)
            and isinstance(tier.get("occurrence"), int)
            and tier["occurrence"] <= occurrence_number
        ]
        if valid_tiers:
            matching_tier = max(valid_tiers, key=lambda tier: tier["occurrence"])

    device = await session.scalar(select(Device).where(Device.id == reservation.device_id))
    lab_id = device.lab_id if device is not None else None
    points_to_deduct = int(matching_tier.get("points", 0)) if matching_tier else 0
    block_days = (
        int(matching_tier.get("block_days", 0)) if matching_tier and lab_id is not None else 0
    )
    penalty = PenaltyCase(
        reservation_id=reservation.id,
        user_id=reservation.user_id,
        college_id=reservation.college_id,
        lab_id=lab_id,
        device_id=reservation.device_id,
        violation_type=violation_type,
        reason=reason[:1000],
        event_at=event_at,
        rule_version_id=version.id if version is not None else None,
        occurrence_number=occurrence_number,
        points_delta=0,
        reservation_block_days=block_days,
        status="ACTIVE",
        confirmed_by=confirmed_by,
        applied_at=utcnow_naive(),
    )
    session.add(penalty)
    await session.flush()

    if user is not None and points_to_deduct:
        penalty.points_delta = await _credit_delta(
            session,
            user=user,
            college_id=reservation.college_id,
            reservation_id=reservation.id,
            delta=-points_to_deduct,
            reason=f"{violation_type}处罚：{reason}"[:500],
            operator_id=confirmed_by,
            event_type=violation_type,
            created_at=penalty.applied_at,
        )

    if block_days > 0 and lab_id is not None:
        session.add(
            ReservationBookingRestriction(
                user_id=reservation.user_id,
                college_id=reservation.college_id,
                scope_type="LAB",
                scope_id=lab_id,
                reason=f"预约 #{reservation.id} 的{violation_type}处罚暂停预约",
                penalty_case_id=penalty.id,
                starts_at=penalty.applied_at,
                ends_at=penalty.applied_at + timedelta(days=block_days),
            )
        )
    affected = (
        await _cancel_other_reservations(session, penalty=penalty, event_at=event_at)
        if block_days > 0
        else []
    )
    append_audit(
        session,
        user_id=confirmed_by,
        college_id=reservation.college_id,
        action="PENALTY_APPLIED",
        target_type="PENALTY_CASE",
        target_id=penalty.id,
        detail={
            "reservation_id": reservation.id,
            "violation_type": violation_type,
            "rule_version": version.version if version else None,
            "occurrence_number": occurrence_number,
            "points_delta": penalty.points_delta,
            "reservation_block_days": block_days,
            "affected_reservation_ids": affected,
        },
    )
    if version is None or matching_tier is None:
        content = (
            f"预约 #{reservation.id} 已记录为{violation_type}。"
            "学院在违规发生时未配置适用处罚阶梯，本次未自动扣分或暂停预约。"
        )
        title = "违规记录已登记"
    else:
        content = (
            f"预约 #{reservation.id} 触发{violation_type}处罚（第 {occurrence_number} 次）："
            f"扣除 {-penalty.points_delta} 分，暂停该实验室预约 {block_days} 天。"
        )
        if affected:
            content += f"另有 {len(affected)} 条尚未开始的预约已取消或驳回，需要时请重新预约。"
        content += "如有异议，可在本次处罚详情中提交申诉。"
        title = "违规处罚已生效"
    enqueue_notification(
        session,
        task_key=f"notification:penalty:{penalty.id}:applied",
        user_id=reservation.user_id,
        college_id=reservation.college_id,
        title=title,
        content=content,
        related_id=penalty.id,
        related_type="PENALTY",
    )
    return penalty


async def assert_reservation_allowed(
    session: AsyncSession,
    *,
    user_id: int,
    college_id: int,
    lab_id: int | None,
    now: datetime,
) -> None:
    conditions = [
        ReservationBookingRestriction.user_id == user_id,
        ReservationBookingRestriction.college_id == college_id,
        ReservationBookingRestriction.released_at.is_(None),
        ReservationBookingRestriction.starts_at <= now,
        or_(
            ReservationBookingRestriction.ends_at.is_(None),
            ReservationBookingRestriction.ends_at > now,
        ),
        or_(
            (ReservationBookingRestriction.scope_type == "COLLEGE")
            & (ReservationBookingRestriction.scope_id == college_id),
            *(
                [
                    (ReservationBookingRestriction.scope_type == "LAB")
                    & (ReservationBookingRestriction.scope_id == lab_id)
                ]
                if lab_id is not None
                else []
            ),
        ),
    ]
    restriction = await session.scalar(
        select(ReservationBookingRestriction)
        .where(*conditions)
        .order_by(ReservationBookingRestriction.starts_at.desc())
        .limit(1)
    )
    if restriction is not None:
        until = restriction.ends_at.isoformat() if restriction.ends_at else None
        raise ApiError(
            "BOOKING_RESTRICTED",
            "当前存在预约限制，请查看通知并联系管理员",
            403,
            data={"blocked_until": until, "scope_type": restriction.scope_type},
        )


async def assert_handover_allowed(
    session: AsyncSession,
    *,
    user_id: int,
    college_id: int | None,
    now: datetime,
) -> None:
    if college_id is None:
        return
    restriction = await session.scalar(
        select(ReservationBookingRestriction.id).where(
            ReservationBookingRestriction.user_id == user_id,
            ReservationBookingRestriction.college_id == college_id,
            ReservationBookingRestriction.scope_type == "COLLEGE",
            ReservationBookingRestriction.scope_id == college_id,
            ReservationBookingRestriction.released_at.is_(None),
            ReservationBookingRestriction.starts_at <= now,
            or_(
                ReservationBookingRestriction.ends_at.is_(None),
                ReservationBookingRestriction.ends_at > now,
            ),
        )
    )
    if restriction is not None:
        raise ApiError(
            "HANDOVER_RESTRICTED",
            "该用户因逾期未还已暂停本学院新领用，请先联系学院负责人",
            409,
        )


async def _notify_overdue_start(
    session: AsyncSession,
    *,
    overdue: ReservationOverdue,
    reservation: Reservation,
) -> None:
    device = await session.scalar(select(Device).where(Device.id == overdue.device_id))
    device_name = device.name if device is not None else f"设备 #{overdue.device_id}"
    enqueue_notification(
        session,
        task_key=f"notification:overdue:{overdue.id}:user:started",
        user_id=overdue.user_id,
        college_id=overdue.college_id,
        title="设备归还已逾期",
        content=(
            f"预约 #{reservation.id} 的设备“{device_name}”尚未提交归还，请尽快办理。"
            f"宽限期至 {overdue.grace_deadline_at:%Y-%m-%d %H:%M}。"
        ),
        related_id=overdue.id,
        related_type="OVERDUE",
        notification_type="RESERVATION_OVERDUE",
        execute_at=overdue.started_at,
    )
    lab_manager_id = (
        await session.scalar(select(Lab.manager_id).where(Lab.id == overdue.lab_id))
        if overdue.lab_id
        else None
    )
    recipient_ids = {lab_manager_id} if lab_manager_id is not None else set()
    for user_id in sorted(recipient_ids):
        enqueue_notification(
            session,
            task_key=f"notification:overdue:{overdue.id}:admin:{user_id}:started",
            user_id=user_id,
            college_id=overdue.college_id,
            title="预约设备逾期未还",
            content=(
                f"用户预约 #{reservation.id} 的设备“{device_name}”已逾期，"
                f"宽限期至 {overdue.grace_deadline_at:%Y-%m-%d %H:%M}。请跟进并记录联系结果。"
            ),
            related_id=overdue.id,
            related_type="OVERDUE",
            notification_type="RESERVATION_OVERDUE",
            execute_at=overdue.started_at,
        )


async def ensure_overdue_started(
    session: AsyncSession,
    reservation: Reservation,
    *,
    now: datetime,
) -> ReservationOverdue | None:
    """Create the overdue case once the reservation's final day has passed."""
    if reservation.status != "IN_USE" or reservation.college_id is None:
        return None
    started_at = business_day_start_utc_naive(reservation.end_date + timedelta(days=1))
    if now < started_at:
        return None
    existing = await session.scalar(
        select(ReservationOverdue)
        .where(ReservationOverdue.reservation_id == reservation.id)
        .with_for_update()
    )
    if existing is not None:
        return existing
    handover = await session.scalar(
        select(DeviceHandover).where(DeviceHandover.reservation_id == reservation.id)
    )
    if (
        handover is not None
        and handover.returned_at is not None
        and handover.returned_at <= started_at
    ):
        return None
    version = await rule_version_at(session, reservation.college_id, started_at)
    grace_days = max(0, int(version.grace_days)) if version is not None else 0
    device = await session.scalar(select(Device).where(Device.id == reservation.device_id))
    overdue = ReservationOverdue(
        reservation_id=reservation.id,
        user_id=reservation.user_id,
        college_id=reservation.college_id,
        lab_id=device.lab_id if device is not None else None,
        device_id=reservation.device_id,
        started_at=started_at,
        grace_deadline_at=started_at + timedelta(days=grace_days),
        rule_version_id=version.id if version is not None else None,
        status=(
            "RETURN_PENDING"
            if handover is not None and handover.returned_at is not None
            else "GRACE"
        ),
        created_at=now,
        updated_at=now,
    )
    session.add(overdue)
    await session.flush()
    session.add(
        OutboxTask(
            task_key=f"timeout:overdue:{reservation.id}:penalty",
            task_type="RESERVATION_OVERDUE_PENALTY",
            aggregate_key=f"reservation:{reservation.id}",
            college_id=reservation.college_id,
            payload={"reservation_id": reservation.id, "overdue_id": overdue.id},
            execute_at=max(overdue.grace_deadline_at, now),
        )
    )
    append_audit(
        session,
        user_id=None,
        college_id=reservation.college_id,
        action="RESERVATION_OVERDUE_START",
        target_type="RESERVATION_OVERDUE",
        target_id=overdue.id,
        detail={
            "reservation_id": reservation.id,
            "started_at": started_at.isoformat(),
            "grace_days": grace_days,
            "rule_version": version.version if version else None,
        },
    )
    await _notify_overdue_start(session, overdue=overdue, reservation=reservation)
    return overdue


async def process_overdue_deadline(
    session: AsyncSession,
    reservation: Reservation,
    overdue: ReservationOverdue,
    *,
    now: datetime,
    return_submitted_at: datetime | None = None,
) -> PenaltyCase | None:
    if overdue.resolved_at is not None or overdue.penalty_case_id is not None:
        return None
    if now < overdue.grace_deadline_at:
        return None
    handover = await session.scalar(
        select(DeviceHandover)
        .where(DeviceHandover.reservation_id == reservation.id)
        .with_for_update()
    )
    submitted_at = (
        handover.returned_at
        if handover is not None and handover.returned_at is not None
        else return_submitted_at
    )
    if submitted_at is not None:
        if submitted_at <= overdue.grace_deadline_at:
            if overdue.escalated_at is None:
                overdue.status = "RETURN_PENDING"
            overdue.updated_at = now
            return None
    penalty = await apply_violation_penalty(
        session,
        reservation,
        violation_type="OVERDUE_RETURN",
        event_at=overdue.grace_deadline_at,
        reason="超过学院设定的归还宽限期仍未提交设备归还",
        # Grace is captured at overdue start, but the sanction itself uses the
        # rule version effective when that grace period expires.
    )
    overdue.penalty_case_id = penalty.id if penalty is not None else None
    if overdue.escalated_at is None:
        overdue.status = "PENALIZED"
    overdue.updated_at = now
    append_audit(
        session,
        user_id=None,
        college_id=overdue.college_id,
        action="RESERVATION_OVERDUE_PENALTY_CHECK",
        target_type="RESERVATION_OVERDUE",
        target_id=overdue.id,
        detail={"penalty_case_id": overdue.penalty_case_id},
    )
    return penalty


async def resolve_overdue_after_accept(
    session: AsyncSession,
    *,
    reservation: Reservation,
    operator_id: int,
    now: datetime,
) -> None:
    overdue = await session.scalar(
        select(ReservationOverdue)
        .where(ReservationOverdue.reservation_id == reservation.id)
        .with_for_update()
    )
    if overdue is None or overdue.resolved_at is not None:
        return
    overdue.resolved_at = now
    overdue.status = "RESOLVED"
    overdue.updated_at = now
    restrictions = list(
        (
            await session.scalars(
                select(ReservationBookingRestriction)
                .where(
                    ReservationBookingRestriction.overdue_id == overdue.id,
                    ReservationBookingRestriction.released_at.is_(None),
                )
                .with_for_update()
            )
        ).all()
    )
    for restriction in restrictions:
        restriction.released_at = now
        restriction.release_reason = "逾期设备已归还并验收"
    append_audit(
        session,
        user_id=operator_id,
        college_id=overdue.college_id,
        action="RESERVATION_OVERDUE_RESOLVED",
        target_type="RESERVATION_OVERDUE",
        target_id=overdue.id,
        detail={"reservation_id": reservation.id, "released_restrictions": len(restrictions)},
    )
