"""Operational statistics and scoped exports."""

import csv
import io
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v2.schemas import ExportTaskData
from app.application.exports import (
    export_rows,
    managed_device_ids,
    safe_csv_row,
    scope_fingerprint,
)
from app.application.lifecycle import append_audit
from app.auth.security import Principal, get_current_principal
from app.common.response import ApiResponse
from app.core.errors import ApiError
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.db.models import (
    Device,
    DeviceStatusHistory,
    ExportTask,
    OutboxTask,
    RepairReport,
    Reservation,
    ReservationBlackout,
    ReservationWaitlist,
)
from app.infrastructure.db.session import get_db

router = APIRouter(dependencies=[Depends(enforce_authenticated_rate_limit)])


ExportType = Literal["devices", "reservations", "repairs"]


class ExportCreateRequest(BaseModel):
    export_type: ExportType
    start_date: date | None = None
    end_date: date | None = None
    status: str | None = Field(default=None, max_length=24)
    college_id: int | None = Field(default=None, gt=0)


def _task_data(request: Request, row: ExportTask) -> ExportTaskData:
    return ExportTaskData(
        id=row.id,
        export_type=row.export_type,
        status=row.status,
        row_count=row.row_count,
        download_url=(
            f"{request.app.state.settings.api_prefix}/reports/exports/{row.id}/download"
            if row.status == "COMPLETED" and row.file_token
            else None
        ),
        error=row.error,
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


def _csv_response(rows: list[dict[str, object]], filename: str) -> StreamingResponse:
    output = io.StringIO()
    if rows:
        writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(safe_csv_row(row) for row in rows)
    else:
        output.write("暂无数据\n")
    body = output.getvalue().encode("utf-8-sig")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/reports/export/{export_type}", include_in_schema=True)
async def direct_export(
    export_type: ExportType,
    request: Request,
    start_date: date | None = None,
    end_date: date | None = None,
    status: str | None = Query(default=None, max_length=24),
    college_id: int | None = Query(default=None, gt=0),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    limit = int(request.app.state.settings.export_sync_row_limit)
    rows = await export_rows(
        session,
        principal,
        export_type,
        {
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "status": status,
            "college_id": college_id,
        },
        max_rows=limit + 1,
    )
    if len(rows) > limit:
        raise ApiError(
            "EXPORT_ASYNC_REQUIRED",
            f"本次导出超过 {limit} 条，请使用异步导出",
            413,
            data={"minimum_row_count": limit + 1},
        )
    append_audit(
        session,
        user_id=principal.user_id,
        college_id=principal.college_id,
        action="REPORT_EXPORT",
        target_type="REPORT",
        target_id=None,
        detail={"export_type": export_type, "row_count": len(rows)},
    )
    await session.commit()
    return _csv_response(rows, f"lab-{export_type}.csv")


@router.get("/reports/summary", response_model=ApiResponse[dict[str, object]])
async def report_summary(
    start_date: date | None = None,
    end_date: date | None = None,
    college_id: int | None = Query(default=None, gt=0),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, object]]:
    end = end_date or date.today()
    start = start_date or end.replace(day=1)
    if end < start:
        raise ApiError("DATE_RANGE_INVALID", "结束日期不能早于开始日期", 422)
    if (end - start).days > 1825:
        raise ApiError("DATE_RANGE_TOO_LARGE", "运营报表一次最多查询 5 年", 422)
    device_ids, _ = await managed_device_ids(session, principal, college_id=college_id)
    device_conditions = []
    if device_ids is not None:
        device_conditions.append(Device.id.in_(device_ids) if device_ids else Device.id == -1)
    device_count = int(
        await session.scalar(select(func.count(Device.id)).where(*device_conditions)) or 0
    )
    reservation_status_rows = (
        await session.execute(
            select(Reservation.status, func.count(Reservation.id))
            .join(Device, Device.id == Reservation.device_id)
            .where(
                *device_conditions,
                Reservation.end_date >= start,
                Reservation.start_date <= end,
            )
            .group_by(Reservation.status)
        )
    ).all()
    repair_status_rows = (
        await session.execute(
            select(RepairReport.status, func.count(RepairReport.id))
            .join(Device, Device.id == RepairReport.device_id)
            .where(
                *device_conditions,
                RepairReport.created_at >= datetime.combine(start, datetime.min.time()),
                RepairReport.created_at
                < datetime.combine(end + timedelta(days=1), datetime.min.time()),
            )
            .group_by(RepairReport.status)
        )
    ).all()
    reservation_counts = Counter(
        {str(status): int(count) for status, count in reservation_status_rows}
    )
    repair_counts = Counter({str(status): int(count) for status, count in repair_status_rows})
    reservation_count = sum(reservation_counts.values())
    repair_count = sum(repair_counts.values())
    device_rows = list(
        (
            await session.execute(
                select(Device.id, Device.college_id, Device.lab_id, Device.status).where(
                    *device_conditions
                )
            )
        ).all()
    )
    scoped_ids = [int(row.id) for row in device_rows]
    start_at = datetime.combine(start, datetime.min.time())
    end_exclusive = datetime.combine(end + timedelta(days=1), datetime.min.time())

    if scoped_ids:
        prior_history = (
            select(
                DeviceStatusHistory.device_id.label("device_id"),
                DeviceStatusHistory.new_status.label("status"),
                func.row_number()
                .over(
                    partition_by=DeviceStatusHistory.device_id,
                    order_by=(DeviceStatusHistory.created_at.desc(), DeviceStatusHistory.id.desc()),
                )
                .label("row_num"),
            )
            .where(
                DeviceStatusHistory.device_id.in_(scoped_ids),
                DeviceStatusHistory.created_at < start_at,
            )
            .subquery()
        )
        prior_states = {
            int(row.device_id): str(row.status)
            for row in (
                await session.execute(
                    select(prior_history.c.device_id, prior_history.c.status).where(
                        prior_history.c.row_num == 1
                    )
                )
            ).all()
        }
        period_history = list(
            (
                await session.execute(
                    select(
                        DeviceStatusHistory.device_id,
                        DeviceStatusHistory.old_status,
                        DeviceStatusHistory.new_status,
                        DeviceStatusHistory.created_at,
                    )
                    .where(
                        DeviceStatusHistory.device_id.in_(scoped_ids),
                        DeviceStatusHistory.created_at >= start_at,
                        DeviceStatusHistory.created_at < end_exclusive,
                    )
                    .order_by(DeviceStatusHistory.created_at, DeviceStatusHistory.id)
                )
            ).all()
        )
        following_history = (
            select(
                DeviceStatusHistory.device_id.label("device_id"),
                DeviceStatusHistory.old_status.label("status"),
                func.row_number()
                .over(
                    partition_by=DeviceStatusHistory.device_id,
                    order_by=(DeviceStatusHistory.created_at, DeviceStatusHistory.id),
                )
                .label("row_num"),
            )
            .where(
                DeviceStatusHistory.device_id.in_(scoped_ids),
                DeviceStatusHistory.created_at >= end_exclusive,
            )
            .subquery()
        )
        following_states = {
            int(row.device_id): str(row.status)
            for row in (
                await session.execute(
                    select(following_history.c.device_id, following_history.c.status).where(
                        following_history.c.row_num == 1
                    )
                )
            ).all()
        }
        lab_ids = sorted({int(row.lab_id) for row in device_rows if row.lab_id is not None})
        college_ids = sorted(
            {int(row.college_id) for row in device_rows if row.college_id is not None}
        )
        blackout_scopes = [
            and_(
                ReservationBlackout.scope_type == "DEVICE",
                ReservationBlackout.scope_id.in_(scoped_ids),
            )
        ]
        if lab_ids:
            blackout_scopes.append(
                and_(
                    ReservationBlackout.scope_type == "LAB",
                    ReservationBlackout.scope_id.in_(lab_ids),
                )
            )
        if college_ids:
            blackout_scopes.append(
                and_(
                    ReservationBlackout.scope_type == "COLLEGE",
                    ReservationBlackout.scope_id.in_(college_ids),
                )
            )
        blackout_rows = list(
            (
                await session.execute(
                    select(
                        ReservationBlackout.scope_type,
                        ReservationBlackout.scope_id,
                        ReservationBlackout.blocked_date,
                    ).where(
                        ReservationBlackout.active.is_(True),
                        ReservationBlackout.blocked_date >= start,
                        ReservationBlackout.blocked_date <= end,
                        or_(*blackout_scopes),
                    )
                )
            ).all()
        )
    else:
        prior_states = {}
        period_history = []
        following_states = {}
        blackout_rows = []

    device_by_id = {int(row.id): row for row in device_rows}
    history_by_device: dict[int, list[object]] = {}
    for item in period_history:
        history_by_device.setdefault(int(item.device_id), []).append(item)
    blocked_by_scope: dict[tuple[str, int], set[date]] = {}
    for scope_type, scope_id, blocked_date in blackout_rows:
        blocked_by_scope.setdefault((str(scope_type), int(scope_id)), set()).add(blocked_date)

    bookable_days: set[tuple[int, date]] = set()
    maintenance_days = 0
    reservable_states = {"IDLE", "IN_USE"}
    day_count = (end - start).days + 1
    for device_id, row in device_by_id.items():
        events = history_by_device.get(device_id, [])
        if device_id in prior_states:
            state = prior_states[device_id]
        elif events:
            state = str(events[0].old_status or row.status)
        else:
            state = following_states.get(device_id, str(row.status))
        event_index = 0
        for offset in range(day_count):
            current_day = start + timedelta(days=offset)
            midnight = datetime.combine(current_day, datetime.min.time())
            next_midnight = midnight + timedelta(days=1)
            while event_index < len(events) and events[event_index].created_at < midnight:
                state = str(events[event_index].new_status)
                event_index += 1
            day_state = state
            end_state = state
            next_index = event_index
            while next_index < len(events) and events[next_index].created_at < next_midnight:
                end_state = str(events[next_index].new_status)
                next_index += 1
            if state == "MAINTENANCE" or any(
                str(events[i].new_status) == "MAINTENANCE" for i in range(event_index, next_index)
            ):
                maintenance_days += 1
            is_blocked = (
                current_day in blocked_by_scope.get(("DEVICE", device_id), set())
                or (
                    row.lab_id is not None
                    and current_day in blocked_by_scope.get(("LAB", int(row.lab_id)), set())
                )
                or (
                    row.college_id is not None
                    and current_day in blocked_by_scope.get(("COLLEGE", int(row.college_id)), set())
                )
            )
            if (
                day_state in reservable_states
                and end_state in reservable_states
                and not is_blocked
                and not any(
                    str(events[i].new_status) not in reservable_states
                    for i in range(event_index, next_index)
                )
            ):
                bookable_days.add((device_id, current_day))
            state = end_state
            event_index = next_index

    occupying_statuses = {"APPROVED", "IN_USE", "COMPLETED", "NO_SHOW"}
    actual_statuses = {"IN_USE", "COMPLETED"}
    reservation_rows = list(
        (
            await session.execute(
                select(
                    Reservation.device_id,
                    Reservation.start_date,
                    Reservation.end_date,
                    Reservation.status,
                    Reservation.check_in_at,
                    Reservation.created_at,
                    Reservation.approved_at,
                ).where(
                    Reservation.device_id.in_(scoped_ids) if scoped_ids else Reservation.id == -1,
                    Reservation.end_date >= start,
                    Reservation.start_date <= end,
                )
            )
        ).all()
    )
    occupied_days: set[tuple[int, date]] = set()
    actual_days: set[tuple[int, date]] = set()
    approval_hours: list[float] = []
    for row in reservation_rows:
        if row.status not in occupying_statuses:
            continue
        first = max(start, row.start_date)
        last = min(end, row.end_date)
        for offset in range((last - first).days + 1):
            current_day = first + timedelta(days=offset)
            key = (int(row.device_id), current_day)
            if key not in bookable_days:
                continue
            occupied_days.add(key)
            if row.status in actual_statuses and row.check_in_at is not None:
                actual_days.add(key)
        if row.approved_at is not None and row.created_at is not None:
            approval_hours.append(
                max(0.0, (row.approved_at - row.created_at).total_seconds() / 3600)
            )

    waitlist_rows = list(
        (
            await session.scalars(
                select(ReservationWaitlist).where(
                    ReservationWaitlist.device_id.in_(scoped_ids)
                    if scoped_ids
                    else ReservationWaitlist.id == -1,
                    ReservationWaitlist.created_at >= start_at,
                    ReservationWaitlist.created_at < end_exclusive,
                )
            )
        ).all()
    )
    converted_waitlist = sum(1 for item in waitlist_rows if item.status == "CONFIRMED")
    capacity = len(bookable_days)
    occupied = len(occupied_days)
    actual_used = len(actual_days)
    occupancy_rate = round(occupied / capacity, 4) if capacity else 0.0
    actual_usage_rate = round(actual_used / capacity, 4) if capacity else 0.0
    return ApiResponse.ok(
        {
            "range": {"startDate": start, "endDate": end},
            "deviceCount": device_count,
            "reservationCount": reservation_count,
            "reservationStatus": dict(reservation_counts),
            "repairCount": repair_count,
            "repairStatus": dict(repair_counts),
            "utilizationRate": occupancy_rate,
            "occupancyRate": occupancy_rate,
            "actualUsageRate": actual_usage_rate,
            "bookableDeviceDays": capacity,
            "occupiedDeviceDays": occupied,
            "actualUsageDeviceDays": actual_used,
            "maintenanceDowntimeDays": maintenance_days,
            "averageApprovalHours": round(sum(approval_hours) / len(approval_hours), 2)
            if approval_hours
            else 0.0,
            "waitlistRequests": len(waitlist_rows),
            "waitlistConverted": converted_waitlist,
            "waitlistConversionRate": round(converted_waitlist / len(waitlist_rows), 4)
            if waitlist_rows
            else 0.0,
            "noShowRate": round(
                reservation_counts.get("NO_SHOW", 0) / max(1, reservation_count),
                4,
            ),
            "violationRate": round(
                reservation_counts.get("VIOLATED", 0) / max(1, reservation_count),
                4,
            ),
        }
    )


@router.post("/reports/exports", response_model=ApiResponse[ExportTaskData], status_code=202)
async def create_export(
    payload: ExportCreateRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ExportTaskData]:
    if not principal.is_lab_admin:
        raise ApiError("FORBIDDEN", "只有负责人或系统管理员可以创建导出任务", 403)
    if payload.start_date and payload.end_date and payload.end_date < payload.start_date:
        raise ApiError("DATE_RANGE_INVALID", "结束日期不能早于开始日期", 422)
    now = datetime.now(UTC).replace(tzinfo=None)
    scope_device_ids, scope_college = await managed_device_ids(
        session,
        principal,
        college_id=payload.college_id,
    )
    filters = {
        "start_date": payload.start_date.isoformat() if payload.start_date else None,
        "end_date": payload.end_date.isoformat() if payload.end_date else None,
        "status": payload.status,
        "college_id": payload.college_id,
        "_scope_fingerprint": scope_fingerprint(scope_device_ids, scope_college),
    }
    row = ExportTask(
        requester_id=principal.user_id,
        college_id=principal.college_id,
        export_type=payload.export_type,
        filters=filters,
        status="PENDING",
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.flush()
    session.add(
        OutboxTask(
            task_key=f"export:{row.id}:generate",
            task_type="EXPORT_GENERATE",
            aggregate_key=f"export:{row.id}",
            college_id=principal.college_id,
            payload={"export_id": row.id},
            execute_at=now,
        )
    )
    append_audit(
        session,
        user_id=principal.user_id,
        college_id=principal.college_id,
        action="REPORT_EXPORT_CREATE",
        target_type="EXPORT",
        target_id=row.id,
        detail={"export_type": payload.export_type},
    )
    await session.commit()
    return ApiResponse.ok(_task_data(request, row))


async def _load_task(
    task_id: int,
    request: Request,
    principal: Principal,
    session: AsyncSession,
) -> ExportTask:
    row = await session.scalar(select(ExportTask).where(ExportTask.id == task_id))
    if row is None:
        raise ApiError("EXPORT_NOT_FOUND", "导出任务不存在或无权访问", 404)
    if principal.is_system_admin:
        return row
    if (
        row.requester_id != principal.user_id
        or not principal.is_lab_admin
        or row.college_id != principal.college_id
    ):
        raise ApiError("EXPORT_NOT_FOUND", "导出任务不存在或无权访问", 404)
    saved_fingerprint = (row.filters or {}).get("_scope_fingerprint")
    if saved_fingerprint:
        current_ids, current_scope = await managed_device_ids(
            session,
            principal,
            college_id=(row.filters or {}).get("college_id"),
        )
        if scope_fingerprint(current_ids, current_scope) != saved_fingerprint:
            raise ApiError("EXPORT_NOT_FOUND", "导出任务不存在或无权访问", 404)
    return row


@router.get("/reports/exports/{task_id}", response_model=ApiResponse[ExportTaskData])
async def export_status(
    task_id: int,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ExportTaskData]:
    row = await _load_task(task_id, request, principal, session)
    return ApiResponse.ok(_task_data(request, row))


@router.get("/reports/exports/{task_id}/download", include_in_schema=False)
async def download_export(
    task_id: int,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
):
    row = await _load_task(task_id, request, principal, session)
    if row.status != "COMPLETED" or not row.file_path:
        raise ApiError("EXPORT_NOT_READY", "导出任务尚未完成", 409)
    root = Path(request.app.state.settings.upload_dir).resolve()
    path = Path(row.file_path).resolve()
    if root not in path.parents or not path.is_file():
        raise ApiError("EXPORT_NOT_FOUND", "导出文件不存在", 404)
    from fastapi.responses import FileResponse

    return FileResponse(path, media_type="text/csv", filename=f"lab-{row.export_type}.csv")
