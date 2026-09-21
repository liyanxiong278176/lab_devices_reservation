from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v2.schemas import FeedbackCreateRequest, FeedbackData
from app.application.lifecycle import append_audit
from app.application.reservations import ReservationService
from app.auth.security import Principal, college_scope, get_current_principal
from app.common.response import ApiResponse
from app.core.errors import ApiError
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.db.models import Reservation, ReservationFeedback
from app.infrastructure.db.session import get_db

router = APIRouter(dependencies=[Depends(enforce_authenticated_rate_limit)])


def _data(row: ReservationFeedback) -> FeedbackData:
    return FeedbackData(
        id=row.id,
        reservation_id=row.reservation_id,
        device_id=row.device_id,
        user_id=row.user_id,
        rating=row.rating,
        comment=row.comment,
        created_at=row.created_at,
    )


async def _load_reservation(session: AsyncSession, reservation_id: int) -> Reservation:
    reservation = await session.scalar(
        select(Reservation)
        .options(selectinload(Reservation.device))
        .where(Reservation.id == reservation_id)
    )
    if reservation is None:
        raise ApiError("RESERVATION_NOT_FOUND", "预约不存在", 404)
    return reservation


async def _can_view(
    session: AsyncSession,
    reservation: Reservation,
    principal: Principal,
) -> bool:
    if principal.is_system_admin or reservation.user_id == principal.user_id:
        scope = college_scope(principal)
        return scope is None or reservation.college_id == scope
    return await ReservationService(session, principal)._can_manage_device(reservation.device)


@router.post(
    "/reservations/{reservation_id}/feedback",
    response_model=ApiResponse[FeedbackData],
    status_code=201,
)
async def create_feedback(
    reservation_id: int,
    payload: FeedbackCreateRequest,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[FeedbackData]:
    reservation = await _load_reservation(session, reservation_id)
    if reservation.user_id != principal.user_id:
        raise ApiError("FORBIDDEN", "只能评价自己的预约", 403)
    if reservation.status != "COMPLETED":
        raise ApiError("FEEDBACK_NOT_READY", "只有完成归还的预约可以评价", 409)
    if await session.scalar(
        select(ReservationFeedback).where(ReservationFeedback.reservation_id == reservation_id)
    ):
        raise ApiError("FEEDBACK_EXISTS", "该预约已经评价过了", 409)
    row = ReservationFeedback(
        reservation_id=reservation.id,
        device_id=reservation.device_id,
        user_id=principal.user_id,
        college_id=reservation.college_id,
        rating=payload.rating,
        comment=payload.comment.strip() if payload.comment else None,
    )
    session.add(row)
    await session.flush()
    append_audit(
        session,
        user_id=principal.user_id,
        college_id=reservation.college_id,
        action="RESERVATION_FEEDBACK",
        target_type="RESERVATION",
        target_id=reservation.id,
        detail={"rating": row.rating},
    )
    await session.commit()
    return ApiResponse.ok(_data(row))


@router.get(
    "/reservations/{reservation_id}/feedback",
    response_model=ApiResponse[FeedbackData | None],
)
async def get_feedback(
    reservation_id: int,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[FeedbackData | None]:
    reservation = await _load_reservation(session, reservation_id)
    if not await _can_view(session, reservation, principal):
        raise ApiError("RESERVATION_NOT_FOUND", "预约不存在或无权访问", 404)
    row = await session.scalar(
        select(ReservationFeedback).where(ReservationFeedback.reservation_id == reservation_id)
    )
    return ApiResponse.ok(_data(row) if row is not None else None)
