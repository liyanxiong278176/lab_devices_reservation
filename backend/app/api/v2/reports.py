"""Operational statistics and scoped exports."""

import csv
import io
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v2.schemas import ExportTaskData
from app.application.exports import export_rows
from app.application.lifecycle import append_audit
from app.auth.security import Principal, get_current_principal
from app.common.response import ApiResponse
from app.core.errors import ApiError
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.db.models import ExportTask, OutboxTask
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
        writer.writerows(rows)
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
    )
    limit = int(request.app.state.settings.export_sync_row_limit)
    if len(rows) > limit:
        raise ApiError(
            "EXPORT_ASYNC_REQUIRED",
            f"本次导出包含 {len(rows)} 条数据，请使用异步导出",
            413,
            data={"row_count": len(rows)},
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
    filters = {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "college_id": college_id,
    }
    devices = await export_rows(session, principal, "devices", filters)
    reservations = await export_rows(session, principal, "reservations", filters)
    repairs = await export_rows(session, principal, "repairs", filters)
    reservation_counts = Counter(str(row.get("状态")) for row in reservations)
    repair_counts = Counter(str(row.get("状态")) for row in repairs)
    occupied = sum(
        (date.fromisoformat(str(row["结束日期"])) - date.fromisoformat(str(row["开始日期"]))).days
        + 1
        for row in reservations
        if row.get("状态") in {"APPROVED", "IN_USE", "COMPLETED"}
    )
    capacity = max(1, len(devices) * ((end - start).days + 1))
    return ApiResponse.ok(
        {
            "range": {"startDate": start, "endDate": end},
            "deviceCount": len(devices),
            "reservationCount": len(reservations),
            "reservationStatus": dict(reservation_counts),
            "repairCount": len(repairs),
            "repairStatus": dict(repair_counts),
            "utilizationRate": round(occupied / capacity, 4),
            "noShowRate": round(
                reservation_counts.get("NO_SHOW", 0) / max(1, len(reservations)),
                4,
            ),
            "violationRate": round(
                reservation_counts.get("VIOLATED", 0) / max(1, len(reservations)),
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
    filters = {
        "start_date": payload.start_date.isoformat() if payload.start_date else None,
        "end_date": payload.end_date.isoformat() if payload.end_date else None,
        "status": payload.status,
        "college_id": payload.college_id,
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
    if row is None or (
        not principal.is_system_admin and row.requester_id != principal.user_id
    ):
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
