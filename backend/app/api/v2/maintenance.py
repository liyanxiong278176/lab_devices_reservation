from __future__ import annotations

import asyncio
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, Header, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v2.schemas import (
    MaintenanceEvidenceData,
    MaintenancePlanData,
    MaintenancePlanPage,
    MaintenancePlanWrite,
    MaintenanceRecordCreate,
    MaintenanceRecordData,
    MaintenanceRecordPage,
)
from app.application.maintenance import MaintenanceService
from app.application.reservations import ReservationService, _device_summary
from app.application.scope_access import manageable_device_ids_statement
from app.auth.security import Principal, get_current_principal
from app.common.response import ApiResponse
from app.core.errors import ApiError
from app.core.uploads import upload_quota_guard
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.db.models import (
    Device,
    DeviceMaintenanceRecord,
    UploadAsset,
)
from app.infrastructure.db.pagination import delayed_page_ids, page_metadata, page_offset
from app.infrastructure.db.session import get_db

router = APIRouter(dependencies=[Depends(enforce_authenticated_rate_limit)])

ALLOWED_EVIDENCE = {
    "application/pdf": (".pdf", b"%PDF-"),
    "image/jpeg": (".jpg", b"\xff\xd8\xff"),
    "image/png": (".png", b"\x89PNG\r\n\x1a\n"),
}


def _service(request: Request, session: AsyncSession, principal: Principal) -> MaintenanceService:
    return MaintenanceService(session, principal, request.app)


def _upload_root(request: Request) -> Path:
    root = Path(request.app.state.settings.upload_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


@router.get("/maintenance-devices", response_model=ApiResponse[dict[str, object]])
async def list_maintenance_devices(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=100),
    search: str | None = Query(default=None, max_length=100),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, object]]:
    if not principal.has_permission("maintenance:manage"):
        raise ApiError("FORBIDDEN", "只有负责人可以管理维护计划", 403)
    page_offset(page, page_size)
    conditions = [
        Device.status != "DELETED",
        Device.id.in_(manageable_device_ids_statement(principal)),
    ]
    if search and search.strip():
        keyword = search.strip()
        conditions.append(
            or_(
                Device.name.contains(keyword, autoescape=True),
                Device.asset_code.contains(keyword, autoescape=True),
            )
        )
    id_query = select(Device.id).where(*conditions)
    count_query = select(func.count(Device.id)).where(*conditions)
    total = int(await session.scalar(count_query) or 0)
    page_ids = delayed_page_ids(id_query, Device.id, page=page, page_size=page_size)
    devices = list(
        (
            await session.scalars(
                select(Device)
                .join(page_ids, page_ids.c.id == Device.id)
                .options(
                    selectinload(Device.lab),
                    selectinload(Device.college),
                    selectinload(Device.category),
                )
                .order_by(Device.id.desc())
            )
        ).all()
    )
    warnings = await ReservationService(session, principal)._maintenance_warnings(
        [device.id for device in devices]
    )
    pages, truncated = page_metadata(total, page_size)
    return ApiResponse.ok(
        {
            "items": [_device_summary(device, warnings.get(device.id)) for device in devices],
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
            "truncated": truncated,
        }
    )


@router.get("/maintenance-plans", response_model=ApiResponse[MaintenancePlanPage])
async def list_maintenance_plans(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    device_id: int | None = Query(default=None, gt=0),
    active: bool | None = Query(default=None),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[MaintenancePlanPage]:
    result = await _service(request, session, principal).list_plans(
        page=page,
        page_size=page_size,
        device_id=device_id,
        active=active,
    )
    return ApiResponse.ok(result)


@router.post(
    "/devices/{device_id}/maintenance-plans",
    response_model=ApiResponse[MaintenancePlanData],
    status_code=201,
)
async def create_maintenance_plan(
    device_id: int,
    payload: MaintenancePlanWrite,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[MaintenancePlanData]:
    result = await _service(request, session, principal).create_plan(device_id, payload)
    return ApiResponse.ok(result)


@router.put(
    "/maintenance-plans/{plan_id}",
    response_model=ApiResponse[MaintenancePlanData],
)
async def update_maintenance_plan(
    plan_id: int,
    payload: MaintenancePlanWrite,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[MaintenancePlanData]:
    result = await _service(request, session, principal).update_plan(plan_id, payload)
    return ApiResponse.ok(result)


@router.get(
    "/maintenance-plans/{plan_id}/records",
    response_model=ApiResponse[MaintenanceRecordPage],
)
async def list_maintenance_records(
    plan_id: int,
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[MaintenanceRecordPage]:
    result = await _service(request, session, principal).list_records(
        plan_id,
        page=page,
        page_size=page_size,
    )
    return ApiResponse.ok(result)


@router.post(
    "/maintenance-plans/{plan_id}/records",
    response_model=ApiResponse[MaintenanceRecordData],
    status_code=201,
)
async def complete_maintenance_cycle(
    plan_id: int,
    payload: MaintenanceRecordCreate,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[MaintenanceRecordData]:
    result = await _service(request, session, principal).complete_cycle(
        plan_id,
        payload,
        idempotency_key=idempotency_key,
    )
    return ApiResponse.ok(result)


@router.post(
    "/devices/{device_id}/maintenance-evidence",
    response_model=ApiResponse[MaintenanceEvidenceData],
    status_code=201,
)
async def upload_maintenance_evidence(
    device_id: int,
    request: Request,
    file: UploadFile = File(...),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[MaintenanceEvidenceData]:
    service = _service(request, session, principal)
    device = await service._managed_device(device_id)
    content_type = (file.content_type or "").lower()
    specification = ALLOWED_EVIDENCE.get(content_type)
    if specification is None:
        raise ApiError("UPLOAD_TYPE_INVALID", "维护凭证只支持 PDF、JPG 或 PNG", 422)
    suffix, signature = specification
    content = await file.read(int(request.app.state.settings.upload_max_bytes) + 1)
    if len(content) > int(request.app.state.settings.upload_max_bytes):
        raise ApiError("UPLOAD_TOO_LARGE", "维护凭证超过系统附件大小限制", 413)
    if not content.startswith(signature):
        raise ApiError("UPLOAD_CONTENT_INVALID", "文件内容与声明类型不匹配", 422)

    path: Path | None = None
    try:
        async with upload_quota_guard(
            request,
            session,
            user_id=principal.user_id,
            college_id=device.college_id,
            incoming_bytes=len(content),
        ):
            token = secrets.token_urlsafe(32)
            path = _upload_root(request) / f"{token}{suffix}"
            await asyncio.to_thread(path.write_bytes, content)
            filename = Path(file.filename or "evidence").name
            filename = filename.replace("\r", "").replace("\n", "")[:255] or "evidence"
            asset = UploadAsset(
                asset_token=token,
                user_id=principal.user_id,
                college_id=device.college_id,
                original_name=filename,
                content_type=content_type,
                size_bytes=len(content),
                storage_path=str(path),
            )
            session.add(asset)
            await session.flush()
            await session.commit()
    except Exception:
        await session.rollback()
        if path is not None:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        raise

    return ApiResponse.ok(
        MaintenanceEvidenceData(
            asset_token=asset.asset_token,
            name=asset.original_name,
            content_type=asset.content_type,
            size_bytes=asset.size_bytes,
            url=f"{request.app.state.settings.api_prefix}/maintenance-evidence/{asset.asset_token}",
        )
    )


@router.get("/maintenance-evidence/{asset_token}", include_in_schema=False)
async def download_maintenance_evidence(
    asset_token: str,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> FileResponse:
    if not principal.has_permission("maintenance:manage"):
        raise ApiError("FORBIDDEN", "只有负责人可以查看维护凭证", 403)
    row = await session.execute(
        select(UploadAsset, DeviceMaintenanceRecord.device_id)
        .join(
            DeviceMaintenanceRecord,
            DeviceMaintenanceRecord.evidence_asset_id == UploadAsset.id,
        )
        .where(UploadAsset.asset_token == asset_token)
    )
    asset, device_id = row.first() or (None, None)
    if asset is None or device_id is None:
        raise ApiError("EVIDENCE_NOT_FOUND", "维护凭证不存在或无权访问", 404)
    device = await ReservationService(session, principal)._load_device(device_id)
    if not await ReservationService(session, principal)._can_manage_device(device):
        raise ApiError("EVIDENCE_NOT_FOUND", "维护凭证不存在或无权访问", 404)
    root = _upload_root(request)
    path = Path(asset.storage_path).resolve()
    if root not in path.parents or not path.is_file():
        raise ApiError("EVIDENCE_NOT_FOUND", "维护凭证文件不存在", 404)
    return FileResponse(path, media_type=asset.content_type, filename=asset.original_name)
