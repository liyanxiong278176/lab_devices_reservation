from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v2.schemas import RepairData, RepairPage
from app.application.repairs import RepairService
from app.auth.security import Principal, get_current_principal
from app.common.response import ApiResponse
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.db.session import get_db

router = APIRouter(dependencies=[Depends(enforce_authenticated_rate_limit)])


class RepairCreateRequest(BaseModel):
    device_id: int = Field(gt=0)
    title: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    image_urls: list[str] | None = Field(default=None, max_length=6)


class RepairHandleRequest(BaseModel):
    resolution_note: str = Field(min_length=2, max_length=1000)


@router.post("/repair-reports", response_model=ApiResponse[RepairData], status_code=201)
async def create_repair(
    payload: RepairCreateRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[RepairData]:
    return ApiResponse.ok(
        await RepairService(session, principal, request.app).create(
            device_id=payload.device_id,
            title=payload.title,
            description=payload.description,
            image_urls=payload.image_urls,
        )
    )


@router.get("/repair-reports/mine", response_model=ApiResponse[RepairPage])
async def my_repairs(
    request: Request,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    cursor: int | None = Query(default=None, ge=1),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[RepairPage]:
    return ApiResponse.ok(
        await RepairService(session, principal, request.app).mine(page, size, cursor)
    )


@router.get("/repair-reports", response_model=ApiResponse[RepairPage])
async def managed_repairs(
    request: Request,
    status: str | None = Query(default=None, max_length=20),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    cursor: int | None = Query(default=None, ge=1),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[RepairPage]:
    return ApiResponse.ok(
        await RepairService(session, principal, request.app).managed(
            status=status,
            page=page,
            page_size=size,
            cursor=cursor,
        )
    )


@router.post("/repair-reports/{report_id}/take", response_model=ApiResponse[RepairData])
async def take_repair(
    report_id: int,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[RepairData]:
    return ApiResponse.ok(await RepairService(session, principal, request.app).take(report_id))


@router.post("/repair-reports/{report_id}/resolve", response_model=ApiResponse[RepairData])
async def resolve_repair(
    report_id: int,
    payload: RepairHandleRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[RepairData]:
    return ApiResponse.ok(
        await RepairService(session, principal, request.app).resolve(
            report_id,
            payload.resolution_note,
        )
    )


@router.post("/repair-reports/{report_id}/reject", response_model=ApiResponse[RepairData])
async def reject_repair(
    report_id: int,
    payload: RepairHandleRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[RepairData]:
    return ApiResponse.ok(
        await RepairService(session, principal, request.app).reject(
            report_id,
            payload.resolution_note,
        )
    )
