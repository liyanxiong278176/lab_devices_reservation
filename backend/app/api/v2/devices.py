from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v2.schemas import AvailabilityDay, DeviceDetail, DeviceSummary
from app.application.reservations import ReservationService
from app.auth.security import Principal, get_current_principal
from app.common.response import ApiResponse
from app.core.errors import ApiError
from app.infrastructure.cache.cache import CacheService
from app.infrastructure.cache.invalidation import (
    enqueue_catalog_cache_bump,
    sync_catalog_cache_bump,
)
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.cache.redis import get_redis, get_redis_circuit
from app.infrastructure.db.models import College, Device, DeviceCategory, Lab, Reservation
from app.infrastructure.db.session import get_db

router = APIRouter(dependencies=[Depends(enforce_authenticated_rate_limit)])


class DeviceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    lab_id: int = Field(gt=0)
    category_id: int | None = Field(default=None, gt=0)
    brand: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)
    specs: str | None = Field(default=None, max_length=500)
    image_url: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=5000)
    need_approval: bool = False
    max_reservation_days: int = Field(default=8, ge=1, le=31)
    tags: list[str] | None = None


class DeviceUpdateRequest(DeviceCreateRequest):
    pass


class DeviceStatusRequest(BaseModel):
    status: str = Field(pattern="^(IDLE|MAINTENANCE|DISABLED|OFFLINE|RETIRED)$")


async def _manager_can_access(
    session: AsyncSession,
    principal: Principal,
    lab: Lab,
) -> bool:
    if principal.is_system_admin:
        return True
    if not principal.is_lab_admin or lab.college_id != principal.college_id:
        return False
    if lab.manager_id == principal.user_id:
        return True
    manager_id = await session.scalar(
        select(College.manager_id).where(College.id == lab.college_id)
    )
    return manager_id == principal.user_id


@router.get("/devices", response_model=ApiResponse[dict[str, object]])
async def list_devices(
    request: Request,
    search: str | None = Query(default=None, max_length=100),
    lab_id: int | None = Query(default=None, gt=0),
    status: str | None = Query(default=None, max_length=20),
    page: int = Query(default=1, ge=1, le=10000),
    page_size: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, object]]:
    cache = CacheService(
        get_redis(request),
        request.app.state.settings,
        getattr(request.app.state, "metrics", None),
        get_redis_circuit(request.app),
    )
    service = ReservationService(session, principal, cache=cache)
    items, total = await service.list_devices(
        search=search,
        lab_id=lab_id,
        status=status,
        page=page,
        page_size=page_size,
    )
    return ApiResponse.ok({"items": items, "total": total, "page": page, "page_size": page_size})


@router.get("/devices/{device_id}", response_model=ApiResponse[DeviceDetail])
async def get_device(
    device_id: int,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[DeviceDetail]:
    return ApiResponse.ok(await ReservationService(session, principal).get_device(device_id))


@router.get("/devices/{device_id}/availability", response_model=ApiResponse[list[AvailabilityDay]])
async def device_availability(
    device_id: int,
    start_date: str,
    end_date: str,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[list[AvailabilityDay]]:
    from datetime import date

    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError as exc:
        raise ApiError("DATE_INVALID", "日期必须使用 YYYY-MM-DD 格式", 422) from exc
    data = await ReservationService(session, principal).availability(device_id, start, end)
    return ApiResponse.ok(data)


@router.post("/devices", response_model=ApiResponse[DeviceSummary], status_code=201)
async def create_device(
    request: Request,
    payload: DeviceCreateRequest,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[DeviceSummary]:
    lab = await session.scalar(
        select(Lab)
        .options(selectinload(Lab.college))
        .where(Lab.id == payload.lab_id, Lab.status == 1)
    )
    if lab is None or not await _manager_can_access(session, principal, lab):
        raise ApiError("FORBIDDEN", "只能管理自己负责实验室或学院的设备", 403)
    device = Device(
        college_id=lab.college_id,
        lab_id=lab.id,
        name=payload.name.strip(),
        brand=payload.brand,
        model=payload.model,
        specs=payload.specs,
        image_url=payload.image_url,
        category_id=payload.category_id,
        description=payload.description,
        need_approval=payload.need_approval,
        max_reservation_days=payload.max_reservation_days,
        tags=payload.tags,
        status="IDLE",
    )
    session.add(device)
    enqueue_catalog_cache_bump(session, lab.college_id)
    await session.commit()
    await sync_catalog_cache_bump(request.app, lab.college_id)
    device.lab = lab
    device.college = lab.college
    return ApiResponse.ok(
        DeviceSummary(
            id=device.id,
            name=device.name,
            status=device.status,
            brand=device.brand,
            model=device.model,
            specs=device.specs,
            image_url=device.image_url,
            lab_id=device.lab_id,
            lab_name=lab.name,
            college_id=device.college_id,
            college_name=lab.college.name if lab.college else None,
            need_approval=device.need_approval,
            max_reservation_days=device.max_reservation_days,
            tags=device.tags,
            category_name=None,
        )
    )


@router.put("/devices/{device_id}", response_model=ApiResponse[DeviceDetail])
async def update_device(
    device_id: int,
    request: Request,
    payload: DeviceUpdateRequest,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[DeviceDetail]:
    service = ReservationService(session, principal)
    device = await service._load_device(device_id)
    if not await service._can_manage_device(device):
        raise ApiError("FORBIDDEN", "只能管理自己负责实验室或学院的设备", 403)
    lab = await session.scalar(
        select(Lab)
        .options(selectinload(Lab.college))
        .where(Lab.id == payload.lab_id, Lab.status == 1)
    )
    if (
        lab is None
        or lab.college_id != device.college_id
        or not await _manager_can_access(
            session,
            principal,
            lab,
        )
    ):
        raise ApiError("FORBIDDEN", "设备只能归属当前负责人管理范围内的实验室", 403)
    if payload.category_id is not None:
        category = await session.scalar(
            select(DeviceCategory).where(DeviceCategory.id == payload.category_id)
        )
        if category is None:
            raise ApiError("CATEGORY_NOT_FOUND", "设备分类不存在", 422)
    device.name = payload.name.strip()
    device.lab_id = lab.id
    device.category_id = payload.category_id
    device.brand = payload.brand
    device.model = payload.model
    device.specs = payload.specs
    device.image_url = payload.image_url
    device.description = payload.description
    device.need_approval = payload.need_approval
    device.max_reservation_days = payload.max_reservation_days
    device.tags = payload.tags
    enqueue_catalog_cache_bump(session, device.college_id)
    await session.commit()
    await sync_catalog_cache_bump(request.app, device.college_id)
    return ApiResponse.ok(await service.get_device(device_id))


@router.delete("/devices/{device_id}", response_model=ApiResponse[None])
async def delete_device(
    device_id: int,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    service = ReservationService(session, principal)
    device = await service._load_device(device_id)
    if not await service._can_manage_device(device):
        raise ApiError("FORBIDDEN", "只能管理自己负责实验室或学院的设备", 403)
    active_count = int(
        await session.scalar(
            select(func.count(Reservation.id)).where(
                Reservation.device_id == device_id,
                Reservation.status.in_(("PENDING", "APPROVED", "IN_USE")),
            )
        )
        or 0
    )
    if active_count:
        raise ApiError("DEVICE_HAS_ACTIVE_RESERVATIONS", "设备仍有有效预约，不能删除", 409)
    device.status = "DELETED"
    enqueue_catalog_cache_bump(session, device.college_id)
    await session.commit()
    await sync_catalog_cache_bump(request.app, device.college_id)
    return ApiResponse.ok(None)


@router.patch("/devices/{device_id}/status", response_model=ApiResponse[DeviceSummary])
async def update_device_status(
    device_id: int,
    request: Request,
    payload: DeviceStatusRequest,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[DeviceSummary]:
    service = ReservationService(session, principal)
    device = await service._load_device(device_id)
    if not await service._can_manage_device(device):
        raise ApiError("FORBIDDEN", "只能管理自己负责实验室或学院的设备", 403)
    device.status = payload.status
    enqueue_catalog_cache_bump(session, device.college_id)
    await session.commit()
    await sync_catalog_cache_bump(request.app, device.college_id)
    return ApiResponse.ok(await service.get_device(device_id))
