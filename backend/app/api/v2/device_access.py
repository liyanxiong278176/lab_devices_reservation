"""Device safety-document acknowledgement and qualification workflows."""

import asyncio
import secrets
from datetime import UTC, date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v2.schemas import (
    DeviceDocumentData,
    QualificationData,
    QualificationReviewRequest,
    QualificationSubmitRequest,
    QualificationUploadData,
    SafetyAcknowledgementRequest,
)
from app.application.lifecycle import append_audit
from app.application.reservations import ReservationService
from app.auth.security import Principal, get_current_principal
from app.common.response import ApiResponse
from app.core.errors import ApiError
from app.core.uploads import upload_quota_guard
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.db.models import (
    DeviceDocument,
    DeviceDocumentAcknowledgement,
    DeviceQualification,
    UploadAsset,
)
from app.infrastructure.db.session import get_db

router = APIRouter(dependencies=[Depends(enforce_authenticated_rate_limit)])

ALLOWED_QUALIFICATION_UPLOADS = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def _upload_root(request: Request) -> Path:
    root = Path(request.app.state.settings.upload_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _qualification_signature_matches(content_type: str, content: bytes) -> bool:
    if content_type == "application/pdf":
        return content.startswith(b"%PDF-")
    if content_type == "image/jpeg":
        return content.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    return content.startswith(b"RIFF") and content[8:12] == b"WEBP"


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _doc_data(request: Request, document: DeviceDocument) -> DeviceDocumentData:
    asset = document.asset
    return DeviceDocumentData(
        id=document.id,
        device_id=document.device_id,
        document_type=document.document_type,
        title=document.title,
        version=document.version,
        requires_ack=document.requires_ack,
        original_name=asset.original_name,
        content_type=asset.content_type,
        size_bytes=asset.size_bytes,
        url=f"{request.app.state.settings.api_prefix}/device-documents/{asset.asset_token}",
        created_by=document.created_by,
        created_at=document.created_at,
        published_at=document.published_at,
    )


def _qualification_data(row: DeviceQualification) -> QualificationData:
    return QualificationData(
        id=row.id,
        device_id=row.device_id,
        user_id=row.user_id,
        status=row.status,
        qualification_type=row.qualification_type,
        asset_id=row.asset_id,
        valid_until=row.valid_until,
        reviewed_by=row.reviewed_by,
        reviewed_at=row.reviewed_at,
        note=row.note,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _service(
    session: AsyncSession,
    principal: Principal,
) -> ReservationService:
    return ReservationService(session, principal)


@router.get(
    "/devices/{device_id}/safety-documents",
    response_model=ApiResponse[list[DeviceDocumentData]],
)
async def safety_documents(
    device_id: int,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[list[DeviceDocumentData]]:
    service = await _service(session, principal)
    device = await service._load_device(device_id)
    rows = list(
        (
            await session.scalars(
                select(DeviceDocument)
                .options(selectinload(DeviceDocument.asset))
                .where(
                    DeviceDocument.device_id == device.id,
                    DeviceDocument.active.is_(True),
                    DeviceDocument.requires_ack.is_(True),
                )
                .order_by(DeviceDocument.document_type, DeviceDocument.id.desc())
            )
        ).all()
    )
    latest: list[DeviceDocument] = []
    seen: set[str] = set()
    for row in rows:
        if row.document_type not in seen:
            latest.append(row)
            seen.add(row.document_type)
    return ApiResponse.ok([_doc_data(request, row) for row in latest])


@router.post(
    "/devices/{device_id}/safety-ack",
    response_model=ApiResponse[dict[str, object]],
)
async def acknowledge_safety(
    device_id: int,
    payload: SafetyAcknowledgementRequest,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, object]]:
    service = await _service(session, principal)
    device = await service._load_device(device_id)
    rows = list(
        (
            await session.scalars(
                select(DeviceDocument)
                .where(
                    DeviceDocument.device_id == device.id,
                    DeviceDocument.active.is_(True),
                    DeviceDocument.requires_ack.is_(True),
                )
                .order_by(DeviceDocument.document_type, DeviceDocument.id.desc())
            )
        ).all()
    )
    latest: list[DeviceDocument] = []
    seen: set[str] = set()
    for row in rows:
        if row.document_type not in seen:
            latest.append(row)
            seen.add(row.document_type)
    if not latest:
        raise ApiError("SAFETY_DOCUMENT_NOT_FOUND", "该设备尚未发布需要确认的安全文档", 409)
    now = _now()
    for document in latest:
        existing = await session.scalar(
            select(DeviceDocumentAcknowledgement).where(
                DeviceDocumentAcknowledgement.document_id == document.id,
                DeviceDocumentAcknowledgement.user_id == principal.user_id,
            )
        )
        if existing is None:
            session.add(
                DeviceDocumentAcknowledgement(
                    document_id=document.id,
                    device_id=device.id,
                    user_id=principal.user_id,
                    college_id=device.college_id,
                    reservation_id=payload.reservation_id,
                    document_version=document.version,
                    acknowledged_at=now,
                )
            )
        else:
            existing.reservation_id = payload.reservation_id
            existing.document_version = document.version
            existing.acknowledged_at = now
    append_audit(
        session,
        user_id=principal.user_id,
        college_id=device.college_id,
        action="DEVICE_SAFETY_ACK",
        target_type="DEVICE",
        target_id=device.id,
        detail={"versions": [row.version for row in latest]},
    )
    await session.commit()
    return ApiResponse.ok(
        {"device_id": device.id, "acknowledged": True, "version": latest[0].version}
    )


@router.post(
    "/devices/{device_id}/qualification-uploads",
    response_model=ApiResponse[QualificationUploadData],
    status_code=201,
)
async def upload_qualification_material(
    device_id: int,
    request: Request,
    file: UploadFile = File(...),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[QualificationUploadData]:
    service = await _service(session, principal)
    device = await service._load_device(device_id)
    content_type = (file.content_type or "").lower()
    suffix = ALLOWED_QUALIFICATION_UPLOADS.get(content_type)
    if suffix is None:
        raise ApiError(
            "QUALIFICATION_UPLOAD_TYPE_INVALID",
            "资质材料只支持 PDF、JPG、PNG 或 WebP",
            422,
        )
    max_bytes = int(request.app.state.settings.upload_max_bytes)
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ApiError("UPLOAD_TOO_LARGE", "资质材料大小不能超过 5 MB", 413)
    if not _qualification_signature_matches(content_type, content):
        raise ApiError("UPLOAD_CONTENT_INVALID", "资质材料内容与文件类型不匹配", 422)
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
        original_name = Path(file.filename or "qualification").name
        original_name = original_name.replace("\r", "").replace("\n", "")[:255] or "qualification"
        asset = UploadAsset(
            asset_token=token,
            user_id=principal.user_id,
            college_id=device.college_id,
            original_name=original_name,
            content_type=content_type,
            size_bytes=len(content),
            storage_path=str(path),
        )
        session.add(asset)
        try:
            await session.commit()
            await session.refresh(asset)
        except Exception:
            await session.rollback()
            await asyncio.to_thread(path.unlink, missing_ok=True)
            raise
    return ApiResponse.ok(
        QualificationUploadData(
            asset_id=asset.id,
            url=f"{request.app.state.settings.api_prefix}/repair-uploads/{token}",
            name=asset.original_name,
            content_type=asset.content_type,
            size_bytes=asset.size_bytes,
        )
    )


@router.get(
    "/devices/{device_id}/qualifications/mine",
    response_model=ApiResponse[QualificationData | None],
)
async def my_qualification(
    device_id: int,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[QualificationData | None]:
    service = await _service(session, principal)
    device = await service._load_device(device_id)
    row = await session.scalar(
        select(DeviceQualification).where(
            DeviceQualification.device_id == device.id,
            DeviceQualification.user_id == principal.user_id,
        )
    )
    return ApiResponse.ok(_qualification_data(row) if row else None)


@router.post(
    "/devices/{device_id}/qualifications",
    response_model=ApiResponse[QualificationData],
    status_code=201,
)
async def submit_qualification(
    device_id: int,
    payload: QualificationSubmitRequest,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[QualificationData]:
    service = await _service(session, principal)
    device = await service._load_device(device_id)
    if payload.asset_id is not None:
        asset = await session.scalar(
            select(UploadAsset).where(
                UploadAsset.id == payload.asset_id,
                UploadAsset.user_id == principal.user_id,
            ).with_for_update()
        )
        if asset is None:
            raise ApiError("QUALIFICATION_ASSET_INVALID", "资质材料不存在或无权使用", 422)
    row = await session.scalar(
        select(DeviceQualification).where(
            DeviceQualification.device_id == device.id,
            DeviceQualification.user_id == principal.user_id,
        )
    )
    now = _now()
    if row is None:
        row = DeviceQualification(
            device_id=device.id,
            user_id=principal.user_id,
            college_id=device.college_id,
            status="PENDING",
            qualification_type=payload.qualification_type.strip(),
            asset_id=payload.asset_id,
            note=payload.note.strip() if payload.note else None,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    else:
        row.status = "PENDING"
        row.qualification_type = payload.qualification_type.strip()
        row.asset_id = payload.asset_id
        row.note = payload.note.strip() if payload.note else None
        row.reviewed_by = None
        row.reviewed_at = None
        row.valid_until = None
        row.updated_at = now
    await session.flush()
    append_audit(
        session,
        user_id=principal.user_id,
        college_id=device.college_id,
        action="DEVICE_QUALIFICATION_SUBMIT",
        target_type="QUALIFICATION",
        target_id=row.id,
        detail={"device_id": device.id},
    )
    await session.commit()
    return ApiResponse.ok(_qualification_data(row))


@router.get(
    "/devices/{device_id}/qualifications",
    response_model=ApiResponse[list[QualificationData]],
)
async def list_qualifications(
    device_id: int,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[list[QualificationData]]:
    service = await _service(session, principal)
    device = await service._load_device(device_id)
    if not await service._can_manage_device(device):
        raise ApiError("FORBIDDEN", "只能查看自己负责范围内的设备资质", 403)
    rows = list(
        (
            await session.scalars(
                select(DeviceQualification)
                .where(DeviceQualification.device_id == device.id)
                .order_by(DeviceQualification.updated_at.desc(), DeviceQualification.id.desc())
            )
        ).all()
    )
    return ApiResponse.ok([_qualification_data(row) for row in rows])


@router.patch(
    "/devices/{device_id}/qualifications/{qualification_id}",
    response_model=ApiResponse[QualificationData],
)
async def review_qualification(
    device_id: int,
    qualification_id: int,
    payload: QualificationReviewRequest,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[QualificationData]:
    service = await _service(session, principal)
    device = await service._load_device(device_id)
    if not await service._can_manage_device(device):
        raise ApiError("FORBIDDEN", "只能审核自己负责范围内的设备资质", 403)
    row = await session.scalar(
        select(DeviceQualification).where(
            DeviceQualification.id == qualification_id,
            DeviceQualification.device_id == device.id,
        )
    )
    if row is None:
        raise ApiError("QUALIFICATION_NOT_FOUND", "资质申请不存在", 404)
    if payload.status == "APPROVED" and payload.valid_until and payload.valid_until < date.today():
        raise ApiError("QUALIFICATION_DATE_INVALID", "资质有效期不能早于今天", 422)
    now = _now()
    row.status = payload.status
    row.valid_until = payload.valid_until if payload.status == "APPROVED" else None
    row.reviewed_by = principal.user_id
    row.reviewed_at = now
    row.note = payload.note.strip() if payload.note else None
    row.updated_at = now
    append_audit(
        session,
        user_id=principal.user_id,
        college_id=device.college_id,
        action="DEVICE_QUALIFICATION_REVIEW",
        target_type="QUALIFICATION",
        target_id=row.id,
        detail={"status": payload.status, "valid_until": str(payload.valid_until)},
    )
    await session.commit()
    return ApiResponse.ok(_qualification_data(row))


@router.get("/devices/{device_id}/access", response_model=ApiResponse[dict[str, object]])
async def device_access(
    device_id: int,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, object]]:
    service = await _service(session, principal)
    snapshot = await service.access_snapshot(device_id)
    return ApiResponse.ok(snapshot)
