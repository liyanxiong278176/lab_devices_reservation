from fastapi import APIRouter, Body, Depends, Header, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v2.schemas import (
    ApprovalRequest,
    ReservationCreateData,
    ReservationData,
    ReservationPage,
    ReservationPlanRequest,
    ReservationPreflightData,
)
from app.application.reservations import ReservationService
from app.auth.security import Principal, get_current_principal
from app.common.response import ApiResponse
from app.core.settings import Settings
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.cache.redis import reservation_lock
from app.infrastructure.db.session import get_db

router = APIRouter(dependencies=[Depends(enforce_authenticated_rate_limit)])


class BatchApprovalRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=100)


def _service(request: Request, session: AsyncSession, principal: Principal) -> ReservationService:
    settings: Settings = request.app.state.settings
    return ReservationService(session, principal, max_days=settings.reservation_max_days)


@router.post("/reservations/preflight", response_model=ApiResponse[ReservationPreflightData])
async def preflight(
    payload: ReservationPlanRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ReservationPreflightData]:
    return ApiResponse.ok(await _service(request, session, principal).preflight(payload))


@router.post("/reservations", response_model=ApiResponse[ReservationCreateData], status_code=201)
async def create_reservation(
    payload: ReservationPlanRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ReservationCreateData]:
    async with reservation_lock(request, payload.device_id, payload.requested_dates()):
        data = await _service(request, session, principal).create(
            payload,
            idempotency_key=idempotency_key,
        )
    return ApiResponse.ok(data)


@router.get("/reservations/mine", response_model=ApiResponse[ReservationPage])
async def my_reservations(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    cursor: int | None = Query(default=None, ge=1),
    status: str | None = Query(default=None, max_length=20),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ReservationPage]:
    return ApiResponse.ok(
        await _service(request, session, principal).list_mine(
            page=page,
            page_size=page_size,
            status=status,
            cursor=cursor,
        )
    )


@router.get("/reservations/{reservation_id}", response_model=ApiResponse[ReservationData])
async def reservation_detail(
    reservation_id: int,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ReservationData]:
    return ApiResponse.ok(
        await _service(request, session, principal).get_reservation(reservation_id)
    )


@router.post("/reservations/{reservation_id}/cancel", response_model=ApiResponse[ReservationData])
async def cancel_reservation(
    reservation_id: int,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ReservationData]:
    return ApiResponse.ok(await _service(request, session, principal).cancel(reservation_id))


@router.post("/reservations/{reservation_id}/check-in", response_model=ApiResponse[ReservationData])
async def check_in(
    reservation_id: int,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ReservationData]:
    return ApiResponse.ok(await _service(request, session, principal).check_in(reservation_id))


@router.post("/reservations/{reservation_id}/return", response_model=ApiResponse[ReservationData])
async def return_device(
    reservation_id: int,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ReservationData]:
    return ApiResponse.ok(await _service(request, session, principal).return_device(reservation_id))


@router.get("/approvals/pending", response_model=ApiResponse[ReservationPage])
async def pending_approvals(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    cursor: int | None = Query(default=None, ge=1),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ReservationPage]:
    return ApiResponse.ok(
        await _service(request, session, principal).pending_approvals(page, page_size, cursor)
    )


@router.post("/approvals/{reservation_id}/approve", response_model=ApiResponse[ReservationData])
async def approve_reservation(
    reservation_id: int,
    request: Request,
    payload: ApprovalRequest | None = Body(default=None),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ReservationData]:
    return ApiResponse.ok(
        await _service(request, session, principal).approve(
            reservation_id,
            True,
            payload.reason if payload else None,
        )
    )


@router.post("/approvals/{reservation_id}/reject", response_model=ApiResponse[ReservationData])
async def reject_reservation(
    reservation_id: int,
    payload: ApprovalRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ReservationData]:
    return ApiResponse.ok(
        await _service(request, session, principal).approve(reservation_id, False, payload.reason)
    )


@router.post("/approvals/batch-approve", response_model=ApiResponse[dict[str, int]])
async def batch_approve(
    payload: BatchApprovalRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, int]]:
    count = await _service(request, session, principal).approve_many(payload.ids)
    return ApiResponse.ok({"approved": count})
