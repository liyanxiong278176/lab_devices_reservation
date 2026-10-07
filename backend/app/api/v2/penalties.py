from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.penalties import PenaltyService
from app.auth.security import Principal, get_current_principal
from app.common.response import ApiResponse
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.db.session import get_db

router = APIRouter(dependencies=[Depends(enforce_authenticated_rate_limit)])


class PenaltyPolicyPayload(BaseModel):
    grace_days: int = Field(ge=0, le=365)
    tiers: dict[str, list[dict[str, int]]]


class GraceBoundsPayload(BaseModel):
    minimum_days: int = Field(ge=0, le=365)
    maximum_days: int = Field(ge=0, le=365)


class AppealPayload(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
    evidence: str | None = Field(default=None, max_length=2000)


class AppealReviewPayload(BaseModel):
    result: str = Field(pattern="^(MAINTAIN|ADJUST|REVOKE)$")
    result_reason: str = Field(min_length=1, max_length=2000)
    points_deduction: int | None = Field(default=None, ge=0, le=100)
    block_days: int | None = Field(default=None, ge=0, le=365)


class OverdueFollowUpPayload(BaseModel):
    result: str = Field(min_length=1, max_length=1000)
    contacted_at: datetime | None = None


class OverdueEscalationPayload(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


def _service(session: AsyncSession, principal: Principal) -> PenaltyService:
    return PenaltyService(session, principal)


@router.get("/penalties/policy", response_model=ApiResponse[dict[str, Any]])
async def get_policy(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    return ApiResponse.ok(await _service(session, principal).get_policy())


@router.put("/penalties/policy", response_model=ApiResponse[dict[str, Any]])
async def save_policy(
    payload: PenaltyPolicyPayload,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    return ApiResponse.ok(
        await _service(session, principal).save_policy(payload.grace_days, payload.tiers)
    )


@router.get("/penalties/system/grace-bounds", response_model=ApiResponse[dict[str, int]])
async def get_grace_bounds(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, int]]:
    return ApiResponse.ok(await _service(session, principal).grace_bounds())


@router.put("/penalties/system/grace-bounds", response_model=ApiResponse[dict[str, int]])
async def update_grace_bounds(
    payload: GraceBoundsPayload,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, int]]:
    return ApiResponse.ok(
        await _service(session, principal).update_grace_bounds(
            payload.minimum_days,
            payload.maximum_days,
        )
    )


@router.get("/penalties/mine", response_model=ApiResponse[list[dict[str, Any]]])
async def my_penalties(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[list[dict[str, Any]]]:
    return ApiResponse.ok(await _service(session, principal).my_cases())


@router.get("/penalties/balance", response_model=ApiResponse[dict[str, int]])
async def my_penalty_balance(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, int]]:
    return ApiResponse.ok(await _service(session, principal).my_balance())


@router.get("/penalties/cases", response_model=ApiResponse[dict[str, Any]])
async def college_penalties(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    return ApiResponse.ok(
        await _service(session, principal).college_cases(page, page_size)
    )


@router.get("/penalties/appeals", response_model=ApiResponse[dict[str, Any]])
async def list_appeals(
    pending_only: bool = Query(default=True),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    return ApiResponse.ok(
        await _service(session, principal).list_appeals(
            pending_only=pending_only,
            page=page,
            page_size=page_size,
        )
    )


@router.post(
    "/penalties/cases/{case_id}/appeals",
    response_model=ApiResponse[dict[str, Any]],
    status_code=201,
)
async def submit_appeal(
    case_id: int,
    payload: AppealPayload,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    return ApiResponse.ok(
        await _service(session, principal).submit_appeal(
            case_id,
            reason=payload.reason,
            evidence=payload.evidence,
        )
    )


@router.post("/penalties/appeals/{appeal_id}/review", response_model=ApiResponse[dict[str, Any]])
async def review_appeal(
    appeal_id: int,
    payload: AppealReviewPayload,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    return ApiResponse.ok(
        await _service(session, principal).review_appeal(
            appeal_id,
            result=payload.result,
            result_reason=payload.result_reason,
            points_deduction=payload.points_deduction,
            block_days=payload.block_days,
        )
    )


@router.get("/penalties/overdue", response_model=ApiResponse[dict[str, Any]])
async def list_overdue(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    return ApiResponse.ok(await _service(session, principal).list_overdue(page, page_size))


@router.post(
    "/penalties/overdue/{overdue_id}/followups",
    response_model=ApiResponse[dict[str, Any]],
    status_code=201,
)
async def add_overdue_followup(
    overdue_id: int,
    payload: OverdueFollowUpPayload,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    return ApiResponse.ok(
        await _service(session, principal).add_followup(
            overdue_id,
            result=payload.result,
            contacted_at=payload.contacted_at,
        )
    )


@router.post(
    "/penalties/overdue/{overdue_id}/escalate",
    response_model=ApiResponse[dict[str, Any]],
)
async def escalate_overdue(
    overdue_id: int,
    payload: OverdueEscalationPayload,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    return ApiResponse.ok(
        await _service(session, principal).escalate_overdue(overdue_id, reason=payload.reason)
    )
