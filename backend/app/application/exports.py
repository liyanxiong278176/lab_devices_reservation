"""Scoped operational exports used by both synchronous HTTP and outbox jobs."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import Principal, college_scope
from app.core.errors import ApiError
from app.infrastructure.db.models import College, Device, Lab, RepairReport, Reservation, User

ExportKind = Literal["devices", "reservations", "repairs"]


def _serial(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    return value


async def managed_device_ids(
    session: AsyncSession,
    principal: Principal,
    *,
    college_id: int | None = None,
) -> tuple[list[int] | None, int | None]:
    if not principal.is_lab_admin:
        raise ApiError("FORBIDDEN", "只有负责人或系统管理员可以导出管理数据", 403)
    if principal.is_system_admin:
        if college_id is None:
            return None, None
        rows = list(
            (
                await session.scalars(
                    select(Device.id).where(Device.college_id == college_id)
                )
            ).all()
        )
        return [int(item) for item in rows], college_id
    scope = college_scope(principal)
    if college_id is not None and college_id != scope:
        raise ApiError("FORBIDDEN", "不能导出其他学院的数据", 403)
    rows = list(
        (
            await session.scalars(
                select(Device.id)
                .outerjoin(Lab, Lab.id == Device.lab_id)
                .join(College, College.id == Device.college_id)
                .where(
                    Device.college_id == scope,
                    or_(
                        Lab.manager_id == principal.user_id,
                        College.manager_id == principal.user_id,
                    ),
                )
            )
        ).all()
    )
    return [int(item) for item in rows], scope


async def export_rows(
    session: AsyncSession,
    principal: Principal,
    kind: ExportKind,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    values = filters or {}
    requested_college = values.get("college_id")
    device_ids, scope = await managed_device_ids(
        session,
        principal,
        college_id=int(requested_college) if requested_college else None,
    )
    start = date.fromisoformat(str(values["start_date"])) if values.get("start_date") else None
    end = date.fromisoformat(str(values["end_date"])) if values.get("end_date") else None
    if start and end and end < start:
        raise ApiError("DATE_RANGE_INVALID", "结束日期不能早于开始日期", 422)

    if kind == "devices":
        conditions: list[Any] = []
        if device_ids is not None:
            conditions.append(Device.id.in_(device_ids) if device_ids else Device.id == -1)
        if values.get("status"):
            conditions.append(Device.status == str(values["status"]))
        rows = list(
            (
                await session.execute(
                    select(
                        Device.id,
                        Device.asset_code,
                        Device.serial_number,
                        Device.name,
                        Device.brand,
                        Device.model,
                        Device.status,
                        Device.risk_level,
                        Device.allow_external_loan,
                        Device.purchase_date,
                        Device.warranty_until,
                        Lab.name.label("lab_name"),
                        College.name.label("college_name"),
                    )
                    .outerjoin(Lab, Lab.id == Device.lab_id)
                    .outerjoin(College, College.id == Device.college_id)
                    .where(*conditions)
                    .order_by(Device.id)
                )
            ).all()
        )
        return [
            {
                "设备ID": row.id,
                "资产编号": row.asset_code,
                "序列号": row.serial_number,
                "设备名称": row.name,
                "品牌": row.brand,
                "型号": row.model,
                "状态": row.status,
                "风险等级": row.risk_level,
                "允许外借": "是" if row.allow_external_loan else "否",
                "购置日期": _serial(row.purchase_date),
                "保修截止": _serial(row.warranty_until),
                "实验室": row.lab_name,
                "学院": row.college_name,
            }
            for row in rows
        ]

    if device_ids is not None and not device_ids:
        return []
    device_condition = Device.id.in_(device_ids) if device_ids is not None else True
    if kind == "reservations":
        conditions = [device_condition]
        if start:
            conditions.append(Reservation.end_date >= start)
        if end:
            conditions.append(Reservation.start_date <= end)
        if values.get("status"):
            conditions.append(Reservation.status == str(values["status"]))
        rows = list(
            (
                await session.execute(
                    select(
                        Reservation.id,
                        Reservation.start_date,
                        Reservation.end_date,
                        Reservation.status,
                        Reservation.purpose,
                        Reservation.created_at,
                        Device.id.label("device_id"),
                        Device.asset_code,
                        Device.name.label("device_name"),
                        Lab.name.label("lab_name"),
                        User.username,
                        User.real_name,
                        College.name.label("college_name"),
                    )
                    .join(Device, Device.id == Reservation.device_id)
                    .outerjoin(Lab, Lab.id == Device.lab_id)
                    .outerjoin(User, User.id == Reservation.user_id)
                    .outerjoin(College, College.id == Device.college_id)
                    .where(*conditions)
                    .order_by(Reservation.id)
                )
            ).all()
        )
        return [
            {
                "预约ID": row.id,
                "设备ID": row.device_id,
                "资产编号": row.asset_code,
                "设备名称": row.device_name,
                "实验室": row.lab_name,
                "预约人": row.real_name or row.username,
                "学院": row.college_name,
                "开始日期": _serial(row.start_date),
                "结束日期": _serial(row.end_date),
                "状态": row.status,
                "用途": row.purpose,
                "提交时间": _serial(row.created_at),
            }
            for row in rows
        ]

    if kind == "repairs":
        conditions = [device_condition]
        if start:
            conditions.append(
                RepairReport.created_at >= datetime.combine(start, datetime.min.time())
            )
        if end:
            conditions.append(
                RepairReport.created_at < datetime.combine(end, datetime.max.time())
            )
        if values.get("status"):
            conditions.append(RepairReport.status == str(values["status"]))
        rows = list(
            (
                await session.execute(
                    select(
                        RepairReport.id,
                        RepairReport.title,
                        RepairReport.priority,
                        RepairReport.status,
                        RepairReport.created_at,
                        RepairReport.taken_at,
                        RepairReport.resolved_at,
                        RepairReport.closed_at,
                        Device.id.label("device_id"),
                        Device.asset_code,
                        Device.name.label("device_name"),
                        User.username,
                        User.real_name,
                        College.name.label("college_name"),
                    )
                    .join(Device, Device.id == RepairReport.device_id)
                    .outerjoin(User, User.id == RepairReport.reporter_id)
                    .outerjoin(College, College.id == Device.college_id)
                    .where(*conditions)
                    .order_by(RepairReport.id)
                )
            ).all()
        )
        return [
            {
                "报修ID": row.id,
                "设备ID": row.device_id,
                "资产编号": row.asset_code,
                "设备名称": row.device_name,
                "报修人": row.real_name or row.username,
                "学院": row.college_name,
                "优先级": row.priority,
                "状态": row.status,
                "提交时间": _serial(row.created_at),
                "受理时间": _serial(row.taken_at),
                "解决时间": _serial(row.resolved_at),
                "关闭时间": _serial(row.closed_at),
                "处理时长(天)": (
                    (row.closed_at - row.created_at).days
                    if row.closed_at and row.created_at
                    else None
                ),
            }
            for row in rows
        ]

    raise ApiError("EXPORT_TYPE_INVALID", "不支持的导出类型", 422)
