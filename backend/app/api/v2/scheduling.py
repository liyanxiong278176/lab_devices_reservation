from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v2.schemas import BlackoutCreateRequest, BlackoutData
from app.application.lifecycle import append_audit
from app.auth.security import Principal, college_scope, get_current_principal
from app.common.response import ApiResponse
from app.core.errors import ApiError
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.db.models import College, Device, Lab, ReservationBlackout
from app.infrastructure.db.session import get_db

router = APIRouter(dependencies=[Depends(enforce_authenticated_rate_limit)])


def _require_manager(principal: Principal) -> None:
    if not principal.is_lab_admin:
        raise ApiError("FORBIDDEN", "只有负责人可以配置不可预约日期", 403)


async def _can_manage_scope(
    session: AsyncSession,
    principal: Principal,
    scope_type: str,
    scope_id: int,
) -> bool:
    if principal.is_system_admin:
        return True
    college_id = college_scope(principal)
    if college_id is None:
        return False
    if scope_type == "COLLEGE":
        return bool(
            await session.scalar(
                select(College.id).where(
                    College.id == scope_id,
                    College.id == college_id,
                    College.manager_id == principal.user_id,
                )
            )
        )
    if scope_type == "LAB":
        return bool(
            await session.scalar(
                select(Lab.id)
                .where(
                    Lab.id == scope_id,
                    Lab.college_id == college_id,
                    or_(
                        Lab.manager_id == principal.user_id,
                        College.manager_id == principal.user_id,
                    ),
                )
                .join(College, College.id == Lab.college_id)
            )
        )
    if scope_type == "DEVICE":
        return bool(
            await session.scalar(
                select(Device.id)
                .outerjoin(Lab, Lab.id == Device.lab_id)
                .join(College, College.id == Device.college_id)
                .where(
                    Device.id == scope_id,
                    Device.college_id == college_id,
                    or_(
                        Lab.manager_id == principal.user_id,
                        College.manager_id == principal.user_id,
                    ),
                )
            )
        )
    return False


def _data(row: ReservationBlackout) -> BlackoutData:
    return BlackoutData(
        id=row.id,
        scope_type=row.scope_type,
        scope_id=row.scope_id,
        blocked_date=row.blocked_date,
        reason=row.reason,
        active=row.active,
        created_at=row.created_at,
    )


@router.get("/blackouts", response_model=ApiResponse[list[BlackoutData]])
async def list_blackouts(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[list[BlackoutData]]:
    scope = college_scope(principal)
    conditions = [ReservationBlackout.active.is_(True)]
    if start_date is not None:
        conditions.append(ReservationBlackout.blocked_date >= start_date)
    if end_date is not None:
        conditions.append(ReservationBlackout.blocked_date <= end_date)
    if scope is not None:
        conditions.append(
            or_(
                (ReservationBlackout.scope_type == "COLLEGE")
                & (ReservationBlackout.scope_id == scope),
                (ReservationBlackout.scope_type == "LAB")
                & ReservationBlackout.scope_id.in_(select(Lab.id).where(Lab.college_id == scope)),
                (ReservationBlackout.scope_type == "DEVICE")
                & ReservationBlackout.scope_id.in_(
                    select(Device.id).where(Device.college_id == scope)
                ),
            )
        )
    rows = list(
        (
            await session.scalars(
                select(ReservationBlackout)
                .where(*conditions)
                .order_by(ReservationBlackout.blocked_date, ReservationBlackout.id)
            )
        ).all()
    )
    return ApiResponse.ok([_data(row) for row in rows])


@router.post("/blackouts", response_model=ApiResponse[BlackoutData], status_code=201)
async def create_blackout(
    payload: BlackoutCreateRequest,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[BlackoutData]:
    _require_manager(principal)
    if not await _can_manage_scope(session, principal, payload.scope_type, payload.scope_id):
        raise ApiError("FORBIDDEN", "只能配置自己负责范围内的不可预约日期", 403)
    duplicate = await session.scalar(
        select(ReservationBlackout).where(
            ReservationBlackout.scope_type == payload.scope_type,
            ReservationBlackout.scope_id == payload.scope_id,
            ReservationBlackout.blocked_date == payload.blocked_date,
        )
    )
    if duplicate is not None:
        if duplicate.active:
            raise ApiError("BLACKOUT_EXISTS", "该范围的日期已经设置为不可预约", 409)
        duplicate.active = True
        duplicate.reason = payload.reason.strip()
        append_audit(
            session,
            user_id=principal.user_id,
            college_id=college_scope(principal),
            action="BLACKOUT_ENABLE",
            target_type="BLACKOUT",
            target_id=duplicate.id,
            detail={
                "scope_type": duplicate.scope_type,
                "blocked_date": duplicate.blocked_date.isoformat(),
            },
        )
        await session.commit()
        return ApiResponse.ok(_data(duplicate))
    row = ReservationBlackout(
        scope_type=payload.scope_type,
        scope_id=payload.scope_id,
        blocked_date=payload.blocked_date,
        reason=payload.reason.strip(),
        active=True,
        created_by=principal.user_id,
    )
    session.add(row)
    await session.flush()
    append_audit(
        session,
        user_id=principal.user_id,
        college_id=college_scope(principal),
        action="BLACKOUT_CREATE",
        target_type="BLACKOUT",
        target_id=row.id,
        detail={"scope_type": row.scope_type, "blocked_date": row.blocked_date.isoformat()},
    )
    await session.commit()
    return ApiResponse.ok(_data(row))


@router.delete("/blackouts/{blackout_id}", response_model=ApiResponse[None])
async def delete_blackout(
    blackout_id: int,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    _require_manager(principal)
    row = await session.scalar(
        select(ReservationBlackout).where(ReservationBlackout.id == blackout_id)
    )
    if row is None or not await _can_manage_scope(session, principal, row.scope_type, row.scope_id):
        raise ApiError("BLACKOUT_NOT_FOUND", "不可预约日期不存在或无权操作", 404)
    row.active = False
    append_audit(
        session,
        user_id=principal.user_id,
        college_id=college_scope(principal),
        action="BLACKOUT_DISABLE",
        target_type="BLACKOUT",
        target_id=row.id,
    )
    await session.commit()
    return ApiResponse.ok(None)
