from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v2.schemas import AvailabilityDay, DeviceDetail, DeviceSummary
from app.application.lifecycle import append_audit, change_device_status
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
from app.infrastructure.db.models import (
    College,
    Device,
    DeviceCategory,
    Lab,
    OutboxTask,
    RepairReport,
    Reservation,
    ReservationItem,
    ReservationRule,
)
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
    accessory_checklist: list[str] = Field(default_factory=list, max_length=30)
    asset_code: str | None = Field(default=None, min_length=2, max_length=80)
    serial_number: str | None = Field(default=None, max_length=120)
    purchase_date: date | None = None
    warranty_until: date | None = None
    allow_external_loan: bool = False
    risk_level: str = Field(default="STANDARD", pattern="^(STANDARD|HIGH|CRITICAL)$")
    requires_safety_ack: bool = False
    requires_qualification: bool = False
    max_advance_days: int | None = Field(default=None, ge=1, le=365)

    @field_validator("accessory_checklist")
    @classmethod
    def normalize_accessories(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values if value.strip()]
        if len(normalized) != len(set(normalized)):
            raise ValueError("配件清单不能包含重复项目")
        if any(len(value) > 100 for value in normalized):
            raise ValueError("单个配件名称不能超过 100 个字符")
        return normalized


class DeviceUpdateRequest(DeviceCreateRequest):
    pass


class DeviceStatusRequest(BaseModel):
    status: str = Field(pattern="^(IDLE|MAINTENANCE|DISABLED|OFFLINE|RETIRED)$")
    reason: str | None = Field(default=None, max_length=500)


async def _manager_can_access(
    session: AsyncSession,
    principal: Principal,
    lab: Lab,
) -> bool:
    if principal.is_system_admin:
        return True
    if not principal.has_permission("device:manage"):
        return False
    if not principal.is_lab_admin or lab.college_id != principal.college_id:
        return False
    if lab.manager_id == principal.user_id:
        return True
    manager_id = await session.scalar(
        select(College.manager_id).where(College.id == lab.college_id)
    )
    return manager_id == principal.user_id


async def _sync_device_reservation_rule(
    session: AsyncSession,
    device: Device,
    user_id: int,
) -> None:
    if session.get_bind().dialect.name == "mysql":
        # The device rule may not exist yet. An atomic upsert avoids both the
        # missing-row gap-lock race and duplicate-key 500s between managers.
        statement = mysql_insert(ReservationRule).values(
            scope_type="DEVICE",
            scope_id=device.id,
            user_category="ALL",
            max_booking_days=device.max_reservation_days,
            max_advance_days=device.max_advance_days,
            approval_required=device.need_approval,
            created_by=user_id,
            updated_by=user_id,
        )
        await session.execute(
            statement.on_duplicate_key_update(
                max_booking_days=statement.inserted.max_booking_days,
                max_advance_days=statement.inserted.max_advance_days,
                approval_required=statement.inserted.approval_required,
                updated_by=user_id,
                updated_at=func.now(),
            )
        )
        return

    rule = await session.scalar(
        select(ReservationRule)
        .where(
            ReservationRule.scope_type == "DEVICE",
            ReservationRule.scope_id == device.id,
            ReservationRule.user_category == "ALL",
        )
        .with_for_update()
    )
    if rule is None:
        new_rule = ReservationRule(
            scope_type="DEVICE",
            scope_id=device.id,
            user_category="ALL",
            created_by=user_id,
            updated_by=user_id,
        )
        try:
            async with session.begin_nested():
                session.add(new_rule)
                await session.flush()
            rule = new_rule
        except IntegrityError:
            # A concurrent reservation-rule upsert may have inserted this row.
            # Roll back only the savepoint so the device update can still commit.
            rule = await session.scalar(
                select(ReservationRule)
                .where(
                    ReservationRule.scope_type == "DEVICE",
                    ReservationRule.scope_id == device.id,
                    ReservationRule.user_category == "ALL",
                )
                .with_for_update()
            )
            if rule is None:
                raise
    rule.max_booking_days = device.max_reservation_days
    rule.max_advance_days = device.max_advance_days
    rule.approval_required = device.need_approval
    rule.updated_by = user_id


@router.get("/devices", response_model=ApiResponse[dict[str, object]])
async def list_devices(
    request: Request,
    search: str | None = Query(default=None, max_length=100),
    lab_id: int | None = Query(default=None, gt=0),
    status: str | None = Query(default=None, max_length=20),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, object]]:
    if not principal.has_permission("device:read"):
        raise ApiError("FORBIDDEN", "当前账号没有查看设备的权限", 403)
    cache = CacheService(
        get_redis(request),
        request.app.state.settings,
        getattr(request.app.state, "metrics", None),
        get_redis_circuit(request.app),
    )
    service = ReservationService(session, principal, cache=cache)
    items, total, pages, truncated = await service.list_devices(
        search=search,
        lab_id=lab_id,
        status=status,
        page=page,
        page_size=page_size,
        include_meta=True,
    )
    return ApiResponse.ok(
        {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
            "truncated": truncated,
        }
    )


@router.get("/devices/{device_id}", response_model=ApiResponse[DeviceDetail])
async def get_device(
    device_id: int,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[DeviceDetail]:
    if not principal.has_permission("device:read"):
        raise ApiError("FORBIDDEN", "当前账号没有查看设备的权限", 403)
    return ApiResponse.ok(await ReservationService(session, principal).get_device(device_id))


@router.get("/devices/{device_id}/availability", response_model=ApiResponse[list[AvailabilityDay]])
async def device_availability(
    device_id: int,
    start_date: str,
    end_date: str,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[list[AvailabilityDay]]:
    if not principal.has_permission("device:read"):
        raise ApiError("FORBIDDEN", "当前账号没有查看设备的权限", 403)
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
        accessory_checklist=payload.accessory_checklist,
        asset_code=payload.asset_code.strip() if payload.asset_code else None,
        serial_number=payload.serial_number.strip() if payload.serial_number else None,
        purchase_date=payload.purchase_date,
        warranty_until=payload.warranty_until,
        allow_external_loan=payload.allow_external_loan,
        risk_level=payload.risk_level,
        requires_safety_ack=payload.requires_safety_ack,
        requires_qualification=payload.requires_qualification,
        max_advance_days=payload.max_advance_days,
        status="IDLE",
    )
    session.add(device)
    await session.flush()
    await _sync_device_reservation_rule(session, device, principal.user_id)
    append_audit(
        session,
        user_id=principal.user_id,
        college_id=lab.college_id,
        action="DEVICE_CREATE",
        target_type="DEVICE",
        target_id=device.id,
        detail={"name": device.name},
    )
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
            accessory_checklist=device.accessory_checklist or [],
            asset_code=device.asset_code,
            serial_number=device.serial_number,
            purchase_date=device.purchase_date,
            warranty_until=device.warranty_until,
            allow_external_loan=device.allow_external_loan,
            risk_level=device.risk_level,
            requires_safety_ack=device.requires_safety_ack,
            requires_qualification=device.requires_qualification,
            max_advance_days=device.max_advance_days,
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
    if not principal.has_permission("device:manage"):
        raise ApiError("FORBIDDEN", "当前账号没有管理设备的权限", 403)
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
    reservation_policy_changed = (
        device.need_approval != payload.need_approval
        or device.max_reservation_days != payload.max_reservation_days
        or device.max_advance_days != payload.max_advance_days
    )
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
    device.accessory_checklist = payload.accessory_checklist
    device.asset_code = payload.asset_code.strip() if payload.asset_code else None
    device.serial_number = payload.serial_number.strip() if payload.serial_number else None
    device.purchase_date = payload.purchase_date
    device.warranty_until = payload.warranty_until
    device.allow_external_loan = payload.allow_external_loan
    device.risk_level = payload.risk_level
    device.requires_safety_ack = payload.requires_safety_ack
    device.requires_qualification = payload.requires_qualification
    device.max_advance_days = payload.max_advance_days
    if reservation_policy_changed:
        await _sync_device_reservation_rule(session, device, principal.user_id)
    append_audit(
        session,
        user_id=principal.user_id,
        college_id=device.college_id,
        action="DEVICE_UPDATE",
        target_type="DEVICE",
        target_id=device.id,
        detail={"name": device.name},
    )
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
    if not principal.has_permission("device:manage"):
        raise ApiError("FORBIDDEN", "当前账号没有管理设备的权限", 403)
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
    change_device_status(
        session,
        device,
        "DELETED",
        operator_id=principal.user_id,
        reason="负责人删除设备",
    )
    append_audit(
        session,
        user_id=principal.user_id,
        college_id=device.college_id,
        action="DEVICE_DELETE",
        target_type="DEVICE",
        target_id=device.id,
    )
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
    if not principal.has_permission("device:manage"):
        raise ApiError("FORBIDDEN", "当前账号没有管理设备的权限", 403)
    service = ReservationService(session, principal)
    device = await service._load_device(device_id)
    if not await service._can_manage_device(device):
        raise ApiError("FORBIDDEN", "只能管理自己负责实验室或学院的设备", 403)
    if payload.status == "IDLE":
        open_repairs = int(
            await session.scalar(
                select(func.count(RepairReport.id)).where(
                    RepairReport.device_id == device_id,
                    RepairReport.status.in_(("PENDING", "PROCESSING")),
                )
            )
            or 0
        )
        if open_repairs:
            raise ApiError("DEVICE_HAS_OPEN_REPAIR", "存在未完成报修，不能恢复为空闲", 409)
    changed = change_device_status(
        session,
        device,
        payload.status,
        operator_id=principal.user_id,
        reason=payload.reason,
    )
    if changed and payload.status in {"MAINTENANCE", "DISABLED", "OFFLINE", "RETIRED"}:
        pending = list(
            (
                await session.scalars(
                    select(Reservation).where(
                        Reservation.device_id == device.id,
                        Reservation.status == "PENDING",
                    )
                )
            ).all()
        )
        for reservation in pending:
            reservation.status = "REJECTED"
            reservation.reject_reason = f"设备已进入{payload.status}状态，暂不可预约"
            await session.execute(
                delete(ReservationItem).where(ReservationItem.reservation_id == reservation.id)
            )
            session.add(
                OutboxTask(
                    task_key=f"notification:reservation:{reservation.id}:device-status-{payload.status.lower()}",
                    task_type="NOTIFICATION",
                    aggregate_key=f"reservation:{reservation.id}",
                    college_id=reservation.college_id,
                    payload={
                        "user_id": reservation.user_id,
                        "college_id": reservation.college_id,
                        "type": "RESERVATION_UPDATE",
                        "title": "预约已驳回",
                        "content": reservation.reject_reason,
                        "related_id": reservation.id,
                        "related_type": "RESERVATION",
                    },
                    execute_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )
        approved = list(
            (
                await session.scalars(
                    select(Reservation).where(
                        Reservation.device_id == device.id,
                        Reservation.status == "APPROVED",
                        Reservation.start_date >= date.today(),
                    )
                )
            ).all()
        )
        for reservation in approved:
            session.add(
                OutboxTask(
                    task_key=f"notification:reservation:{reservation.id}:device-unavailable-{payload.status.lower()}",
                    task_type="NOTIFICATION",
                    aggregate_key=f"reservation:{reservation.id}",
                    college_id=reservation.college_id,
                    payload={
                        "user_id": reservation.user_id,
                        "college_id": reservation.college_id,
                        "type": "RESERVATION_UPDATE",
                        "title": "预约需要调整",
                        "content": (
                            f"设备“{device.name}”已进入{payload.status}状态，原预约暂不能使用，"
                            "请联系负责人取消或更换设备。"
                        ),
                        "related_id": reservation.id,
                        "related_type": "RESERVATION",
                    },
                    execute_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )
    append_audit(
        session,
        user_id=principal.user_id,
        college_id=device.college_id,
        action="DEVICE_STATUS_CHANGE",
        target_type="DEVICE",
        target_id=device.id,
        detail={"status": payload.status, "reason": payload.reason},
    )
    enqueue_catalog_cache_bump(session, device.college_id)
    await session.commit()
    await sync_catalog_cache_bump(request.app, device.college_id)
    return ApiResponse.ok(await service.get_device(device_id))
