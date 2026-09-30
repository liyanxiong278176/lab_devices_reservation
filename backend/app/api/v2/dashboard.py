from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import Principal, college_scope, get_current_principal
from app.common.response import ApiResponse
from app.core.errors import ApiError
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.db.models import (
    College,
    Device,
    DeviceCategory,
    Lab,
    Notification,
    RepairReport,
    Reservation,
    ReservationItem,
)
from app.infrastructure.db.session import get_db

router = APIRouter(dependencies=[Depends(enforce_authenticated_rate_limit)])
ACTIVE_STATUSES = ("PENDING", "APPROVED", "IN_USE")


def _scoped_device_query(principal: Principal):
    stmt = select(Device.id).where(Device.status != "DELETED")
    scope = college_scope(principal)
    if scope is None:
        return stmt
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
    return stmt


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
    today = date.today()
    start = today - timedelta(days=29)
    status_rows = (
        await session.execute(
            select(Reservation.status, func.count(Reservation.id))
            .where(*conditions)
            .group_by(Reservation.status)
        )
    ).all()
    statuses = {str(status): int(count) for status, count in status_rows}
    trend_rows = (
        await session.execute(
            select(Reservation.start_date, func.count(Reservation.id))
            .where(
                *conditions,
                Reservation.start_date.between(start, today),
            )
            .group_by(Reservation.start_date)
        )
    ).all()
    trend = Counter({reservation_date: int(count) for reservation_date, count in trend_rows})
    category_rows = (
        await session.execute(
            select(
                func.coalesce(DeviceCategory.id, 0),
                func.coalesce(DeviceCategory.name, "未分类"),
                func.count(Reservation.id),
            )
            .join(Device, Device.id == Reservation.device_id)
            .outerjoin(DeviceCategory, DeviceCategory.id == Device.category_id)
            .where(*conditions)
            .group_by(DeviceCategory.id, DeviceCategory.name)
        )
    ).all()
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
                {"categoryId": int(category_id), "categoryName": str(name), "count": int(count)}
                for category_id, name, count in category_rows
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
    if not principal.has_permission("report:read"):
        raise ApiError("FORBIDDEN", "当前角色无运营看板权限", 403)
    device_id_query = _scoped_device_query(principal)
    today = date.today()
    start = today - timedelta(days=days - 1)
    device_rows = (
        await session.execute(
            select(
                Device.id,
                Device.name,
                Device.status,
                DeviceCategory.id,
                DeviceCategory.name,
            )
            .outerjoin(DeviceCategory, DeviceCategory.id == Device.category_id)
            .where(Device.id.in_(device_id_query))
        )
    ).all()
    if not device_rows:
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
    device_status = Counter(str(row.status) for row in device_rows)
    reservation_conditions = [
        Reservation.device_id.in_(device_id_query),
        Reservation.start_date.is_not(None),
        Reservation.end_date.is_not(None),
        Reservation.end_date >= start,
        Reservation.start_date <= today,
    ]
    week_start = today - timedelta(days=6)
    daily_rows = (
        await session.execute(
            select(
                Reservation.start_date,
                func.count(Reservation.id),
                func.sum(
                    case(
                        (
                            Reservation.status.notin_(("CANCELLED", "REJECTED")),
                            1,
                        ),
                        else_=0,
                    )
                ),
                func.sum(
                    case(
                        (
                            (Reservation.status.in_(("VIOLATED", "NO_SHOW")))
                            & (Reservation.start_date >= week_start),
                            1,
                        ),
                        else_=0,
                    )
                ),
                func.sum(
                    case(
                        (
                            Reservation.status.in_(ACTIVE_STATUSES)
                            & (Reservation.start_date <= today)
                            & (Reservation.end_date >= today),
                            1,
                        ),
                        else_=0,
                    )
                ),
            )
            .where(*reservation_conditions)
            .group_by(Reservation.start_date)
        )
    ).all()
    trend = Counter(
        {
            reservation_date: int(trend_count or 0)
            for reservation_date, _, trend_count, _, _ in daily_rows
            if start <= reservation_date <= today
        }
    )
    today_reservations = sum(int(row[4] or 0) for row in daily_rows)
    weekly_violations = sum(int(row[3] or 0) for row in daily_rows)
    # Pending approvals are an operational queue, so future reservations must
    # also be counted.  Keep the date-window query above for trends and usage,
    # but do not let that reporting window hide work still awaiting approval.
    pending = int(
        await session.scalar(
            select(func.count(Reservation.id)).where(
                Reservation.device_id.in_(device_id_query),
                Reservation.status == "PENDING",
            )
        )
        or 0
    )
    occupied_rows = (
        await session.execute(
            select(ReservationItem.device_id, func.count(ReservationItem.id))
            .join(Reservation, Reservation.id == ReservationItem.reservation_id)
            .where(
                ReservationItem.device_id.in_(device_id_query),
                ReservationItem.reservation_date.between(start, today),
                Reservation.status.in_(ACTIVE_STATUSES),
            )
            .group_by(ReservationItem.device_id)
        )
    ).all()
    occupied_by_device = {int(device_id): int(count) for device_id, count in occupied_rows}
    util_by_group: dict[tuple[int, str], dict[str, float | int | str]] = {}
    category_counts: Counter[tuple[int, str]] = Counter()
    for device_id, device_name, device_status_value, category_id, category_name in device_rows:
        category_key = (int(category_id or 0), category_name or "未分类")
        category_counts[category_key] += 1
        if group_by == "category":
            key = category_key
            label = key[1]
            group_key = f"category:{key[0]}"
        else:
            key = (int(device_id), str(device_name))
            label = str(device_name)
            group_key = f"device:{device_id}"
        entry = util_by_group.setdefault(
            key,
            {"key": group_key, "label": label, "occupiedSlots": 0, "availableSlots": 0},
        )
        entry["occupiedSlots"] = int(entry["occupiedSlots"]) + occupied_by_device.get(
            int(device_id), 0
        )
        entry["availableSlots"] = int(entry["availableSlots"]) + (
            days
            if device_status_value not in {"MAINTENANCE", "DISABLED", "OFFLINE", "RETIRED"}
            else 0
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
    heatmap = [
        {
            "dayOfWeek": ((reservation_date.weekday() + 1) % 7) + 1,
            "hour": 0,
            "count": count,
        }
        for reservation_date, count, _, _, _ in daily_rows
    ]
    repair_conditions = [RepairReport.device_id.in_(device_id_query)]
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
