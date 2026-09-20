from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.security import Principal, college_scope, get_current_principal
from app.common.response import ApiResponse
from app.core.errors import ApiError
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.db.models import (
    College,
    Device,
    Lab,
    Notification,
    RepairReport,
    Reservation,
    ReservationItem,
)
from app.infrastructure.db.session import get_db

router = APIRouter(dependencies=[Depends(enforce_authenticated_rate_limit)])
ACTIVE_STATUSES = ("PENDING", "APPROVED", "IN_USE")


async def _scoped_device_ids(session: AsyncSession, principal: Principal) -> list[int]:
    stmt = select(Device.id).where(Device.status != "DELETED")
    scope = college_scope(principal)
    if scope is None:
        return [int(value) for value in (await session.scalars(stmt)).all()]
    if principal.is_lab_admin:
        stmt = (
            stmt.outerjoin(Lab, Lab.id == Device.lab_id)
            .join(College, College.id == Device.college_id)
            .where(
                Device.college_id == scope,
                or_(
                    Lab.manager_id == principal.user_id,
                    College.manager_id == principal.user_id,
                ),
            )
        )
    else:
        stmt = stmt.where(Device.college_id == scope)
    return [int(value) for value in (await session.scalars(stmt)).all()]


def _date_series(start: date, end: date, counts: Counter[date]) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    current = start
    while current <= end:
        values.append({"date": current.isoformat(), "count": counts[current]})
        current += timedelta(days=1)
    return values


@router.get("/dashboard/me", response_model=ApiResponse[dict[str, object]])
async def dashboard_me(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, object]]:
    scope = college_scope(principal)
    conditions = [Reservation.user_id == principal.user_id]
    if scope is not None:
        conditions.append(Reservation.college_id == scope)
    reservations = list(
        (
            await session.scalars(
                select(Reservation)
                .options(selectinload(Reservation.device).selectinload(Device.category))
                .where(*conditions)
            )
        ).all()
    )
    statuses = Counter(item.status for item in reservations)
    today = date.today()
    start = today - timedelta(days=29)
    trend = Counter(
        item.start_date
        for item in reservations
        if item.start_date and start <= item.start_date <= today
    )
    category_counts: Counter[tuple[int, str]] = Counter()
    for item in reservations:
        category = item.device.category if item.device else None
        category_counts[
            (category.id if category else 0, category.name if category else "未分类")
        ] += 1
    unread_conditions = [
        Notification.user_id == principal.user_id,
        Notification.is_read.is_(False),
    ]
    if scope is not None:
        unread_conditions.append(Notification.college_id == scope)
    unread = int(
        await session.scalar(select(func.count(Notification.id)).where(*unread_conditions)) or 0
    )
    repair_conditions = [RepairReport.reporter_id == principal.user_id]
    if scope is not None:
        repair_conditions.append(RepairReport.college_id == scope)
    repair_count = int(
        await session.scalar(select(func.count(RepairReport.id)).where(*repair_conditions)) or 0
    )
    return ApiResponse.ok(
        {
            "myReservationsByStatus": dict(statuses),
            "myTrend30d": _date_series(start, today, trend),
            "myCategoryDist": [
                {"categoryId": key[0], "categoryName": key[1], "count": value}
                for key, value in category_counts.items()
            ],
            "unreadCount": unread,
            "myRepairCount": repair_count,
        }
    )


@router.get("/dashboard/overview", response_model=ApiResponse[dict[str, object]])
async def dashboard_overview(
    group_by: str = Query(default="device", alias="groupBy", pattern="^(device|category)$"),
    days: int = Query(default=30, ge=7, le=90),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, object]]:
    if not principal.is_lab_admin and not principal.is_system_admin:
        raise ApiError("FORBIDDEN", "当前角色无运营看板权限", 403)
    device_ids = await _scoped_device_ids(session, principal)
    today = date.today()
    start = today - timedelta(days=days - 1)
    if not device_ids:
        return ApiResponse.ok(
            {
                "deviceStatus": {},
                "trend30d": _date_series(start, today, Counter()),
                "utilization": [],
                "heatmap": [],
                "categoryDist": [],
                "repairStats": {},
                "cards": {"todayReservations": 0, "pendingApprovals": 0, "weeklyViolations": 0},
            }
        )
    devices = list(
        (
            await session.scalars(
                select(Device)
                .options(selectinload(Device.category))
                .where(Device.id.in_(device_ids))
            )
        ).all()
    )
    device_status = Counter(device.status for device in devices)
    reservation_conditions = [
        Reservation.device_id.in_(device_ids),
        Reservation.start_date.is_not(None),
        Reservation.end_date.is_not(None),
        Reservation.end_date >= start,
        Reservation.start_date <= today,
    ]
    reservations = list(
        (await session.scalars(select(Reservation).where(*reservation_conditions))).all()
    )
    trend = Counter(
        item.start_date
        for item in reservations
        if item.start_date
        and start <= item.start_date <= today
        and item.status not in {"CANCELLED", "REJECTED"}
    )
    week_start = today - timedelta(days=6)
    weekly_violations = sum(
        1
        for item in reservations
        if item.status in {"VIOLATED", "NO_SHOW"}
        and item.start_date
        and item.start_date >= week_start
    )
    today_reservations = sum(
        1
        for item in reservations
        if item.status in ACTIVE_STATUSES and item.start_date <= today <= item.end_date
    )
    # Pending approvals are an operational queue, so future reservations must
    # also be counted.  Keep the date-window query above for trends and usage,
    # but do not let that reporting window hide work still awaiting approval.
    pending = int(
        await session.scalar(
            select(func.count(Reservation.id)).where(
                Reservation.device_id.in_(device_ids),
                Reservation.status == "PENDING",
            )
        )
        or 0
    )
    items = list(
        (
            await session.scalars(
                select(ReservationItem)
                .join(Reservation, Reservation.id == ReservationItem.reservation_id)
                .where(
                    ReservationItem.device_id.in_(device_ids),
                    ReservationItem.reservation_date.between(start, today),
                    Reservation.status.in_(ACTIVE_STATUSES),
                )
            )
        ).all()
    )
    occupied_by_device = Counter(item.device_id for item in items)
    util_by_group: dict[tuple[int, str], dict[str, float | int | str]] = {}
    for device in devices:
        category = device.category
        if group_by == "category":
            key = (category.id if category else 0, category.name if category else "未分类")
            label = key[1]
            group_key = f"category:{key[0]}"
        else:
            key = (device.id, device.name)
            label = device.name
            group_key = f"device:{device.id}"
        entry = util_by_group.setdefault(
            key,
            {"key": group_key, "label": label, "occupiedSlots": 0, "availableSlots": 0},
        )
        entry["occupiedSlots"] = int(entry["occupiedSlots"]) + occupied_by_device[device.id]
        entry["availableSlots"] = int(entry["availableSlots"]) + (
            days if device.status not in {"MAINTENANCE", "DISABLED", "OFFLINE", "RETIRED"} else 0
        )
    utilization = [
        {
            **entry,
            "utilizationRate": (
                entry["occupiedSlots"] / entry["availableSlots"] if entry["availableSlots"] else 0
            ),
        }
        for entry in util_by_group.values()
    ]
    category_counts = Counter(
        (
            device.category.id if device.category else 0,
            device.category.name if device.category else "未分类",
        )
        for device in devices
    )
    heatmap = [
        {
            "dayOfWeek": ((reservation_date.weekday() + 1) % 7) + 1,
            "hour": 0,
            "count": count,
        }
        for reservation_date, count in Counter(
            reservation.start_date for reservation in reservations if reservation.start_date
        ).items()
    ]
    repair_conditions = [RepairReport.device_id.in_(device_ids)]
    repair_stats = {
        str(status): int(count)
        for status, count in (
            await session.execute(
                select(RepairReport.status, func.count(RepairReport.id))
                .where(*repair_conditions)
                .group_by(RepairReport.status)
            )
        ).all()
    }
    return ApiResponse.ok(
        {
            "deviceStatus": dict(device_status),
            "trend30d": _date_series(start, today, trend),
            "utilization": utilization,
            "heatmap": heatmap,
            "categoryDist": [
                {"categoryId": key[0], "categoryName": key[1], "deviceCount": value}
                for key, value in category_counts.items()
            ],
            "repairStats": dict(repair_stats),
            "cards": {
                "todayReservations": today_reservations,
                "pendingApprovals": pending,
                "weeklyViolations": weekly_violations,
            },
        }
    )


@router.get("/dashboard/summary", response_model=ApiResponse[dict[str, object]])
async def dashboard_summary(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, object]]:
    return await dashboard_me(principal, session)
