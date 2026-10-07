from fastapi import APIRouter, Body, Depends, Header, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v2.schemas import (
    ApprovalRequest,
    HandoverRequest,
    ReservationCreateData,
    ReservationData,
    ReservationPage,
    ReservationPlanRequest,
    ReservationPreflightData,
    ReturnAcceptanceRequest,
    ReturnInspectionRequest,
    WaitlistConfirmationData,
    WaitlistCreateRequest,
    WaitlistData,
)
from app.application.reservations import ReservationService
from app.auth.security import Principal, get_current_principal
from app.common.response import ApiResponse
from app.core.errors import ApiError
from app.core.settings import Settings
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.cache.redis import get_redis, get_redis_circuit
from app.infrastructure.cache.reservation_quota import (
    ReservationQuotaCache,
    get_reservation_quota_readiness,
)
from app.infrastructure.db.models import ReservationWaitlist
from app.infrastructure.db.session import get_db

router = APIRouter(dependencies=[Depends(enforce_authenticated_rate_limit)])


class BatchApprovalRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=100)


def _service(request: Request, session: AsyncSession, principal: Principal) -> ReservationService:
    settings: Settings = request.app.state.settings
    return ReservationService(
        session,
        principal,
        max_days=settings.reservation_max_days,
        credit_block_threshold=settings.credit_block_threshold,
        credit_block_days=settings.credit_block_days,
        advance_days=settings.reservation_advance_days,
        manager_advance_days=settings.reservation_manager_advance_days,
        reservation_quota=ReservationQuotaCache(
            get_redis(request),
            get_redis_circuit(request.app),
            get_reservation_quota_readiness(request.app),
        ),
    )


@router.post("/reservations/preflight", response_model=ApiResponse[ReservationPreflightData])
async def preflight(
    payload: ReservationPlanRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ReservationPreflightData]:
    return ApiResponse.ok(await _service(request, session, principal).preflight(payload))


@router.post("/reservations/waitlist", response_model=ApiResponse[WaitlistData], status_code=201)
async def join_waitlist(
    payload: WaitlistCreateRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[WaitlistData]:
    return ApiResponse.ok(
        await _service(request, session, principal).join_waitlist(
            device_id=payload.device_id,
            reservation_date=payload.reservation_date,
            purpose=payload.purpose,
            purpose_category=payload.purpose_category,
            project_reference=payload.project_reference,
        )
    )


@router.get("/reservations/waitlist/mine", response_model=ApiResponse[list[WaitlistData]])
async def my_waitlist(
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[list[WaitlistData]]:
    return ApiResponse.ok(await _service(request, session, principal).list_waitlist())


@router.delete("/reservations/waitlist/{entry_id}", response_model=ApiResponse[None])
async def cancel_waitlist(
    entry_id: int,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await _service(request, session, principal).cancel_waitlist(entry_id)
    return ApiResponse.ok(None)


@router.post(
    "/reservations/waitlist/{entry_id}/confirm",
    response_model=ApiResponse[WaitlistConfirmationData],
)
async def confirm_waitlist_offer(
    entry_id: int,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[WaitlistConfirmationData]:
    entry = await session.scalar(
        select(ReservationWaitlist).where(
            ReservationWaitlist.id == entry_id,
            ReservationWaitlist.user_id == principal.user_id,
        )
    )
    if entry is None:
        raise ApiError("WAITLIST_OFFER_NOT_FOUND", "候补预约保留已失效", 409)
    service = _service(request, session, principal)
    data = await service.confirm_waitlist_offer(entry_id)
    return ApiResponse.ok(data)


@router.post("/reservations", response_model=ApiResponse[ReservationCreateData], status_code=201)
async def create_reservation(
    payload: ReservationPlanRequest,
    request: Request,
    idempotency_key: str = Header(
        min_length=1,
        max_length=128,
        alias="Idempotency-Key",
    ),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ReservationCreateData]:
    service = _service(request, session, principal)
    data = await service.create(payload, idempotency_key=idempotency_key)
    return ApiResponse.ok(data)


@router.get("/reservations/mine", response_model=ApiResponse[ReservationPage])
async def my_reservations(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None, max_length=20),
    handover_status: str | None = Query(default=None, max_length=24),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ReservationPage]:
    return ApiResponse.ok(
        await _service(request, session, principal).list_mine(
            page=page,
            page_size=page_size,
            status=status,
            handover_status=handover_status,
        )
    )


@router.get("/reservations/handovers", response_model=ApiResponse[ReservationPage])
async def pending_handovers(
    request: Request,
    status: str = Query(default="PENDING", max_length=20),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ReservationPage]:
    return ApiResponse.ok(
        await _service(request, session, principal).pending_handovers(
            status=status,
            page=page,
            page_size=page_size,
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


@router.post(
    "/reservations/{reservation_id}/cancel-handover-exception",
    response_model=ApiResponse[ReservationData],
)
async def cancel_handover_exception(
    reservation_id: int,
    payload: ApprovalRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ReservationData]:
    return ApiResponse.ok(
        await _service(request, session, principal).cancel_handover_exception(
            reservation_id,
            payload.reason or "交接异常，设备进入维修",
        )
    )


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
    payload: ReturnInspectionRequest,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ReservationData]:
    return ApiResponse.ok(
        await _service(request, session, principal).return_device(
            reservation_id,
            condition=payload.condition,
            note=payload.note,
            image_urls=payload.image_urls,
        )
    )


@router.post(
    "/reservations/{reservation_id}/handover",
    response_model=ApiResponse[ReservationData],
)
async def handover_reservation(
    reservation_id: int,
    request: Request,
    payload: HandoverRequest,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ReservationData]:
    return ApiResponse.ok(
        await _service(request, session, principal).handover(
            reservation_id,
            condition=payload.condition,
            note=payload.note,
            image_urls=payload.image_urls,
            checklist=payload.checklist,
        )
    )


@router.post(
    "/reservations/{reservation_id}/accept-return",
    response_model=ApiResponse[ReservationData],
)
async def accept_return(
    reservation_id: int,
    request: Request,
    payload: ReturnAcceptanceRequest,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ReservationData]:
    return ApiResponse.ok(
        await _service(request, session, principal).accept_return(
            reservation_id,
            condition=payload.condition,
            note=payload.note,
            checklist=payload.checklist,
        )
    )


@router.post("/reservations/{reservation_id}/violate", response_model=ApiResponse[ReservationData])
async def violate_reservation(
    reservation_id: int,
    payload: ApprovalRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ReservationData]:
    reason = (payload.reason or "负责人标记预约违规").strip()
    return ApiResponse.ok(
        await _service(request, session, principal).violate(reservation_id, reason)
    )


@router.get("/approvals/pending", response_model=ApiResponse[ReservationPage])
async def pending_approvals(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ReservationPage]:
    return ApiResponse.ok(
        await _service(request, session, principal).pending_approvals(page, page_size)
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
