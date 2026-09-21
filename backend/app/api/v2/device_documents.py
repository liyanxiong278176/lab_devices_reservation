from __future__ import annotations

import asyncio
import secrets
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v2.schemas import DeviceDocumentData
from app.application.lifecycle import append_audit
from app.application.reservations import ReservationService
from app.auth.security import Principal, college_scope, get_current_principal
from app.common.response import ApiResponse
from app.core.errors import ApiError
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.db.models import DeviceDocument, UploadAsset
from app.infrastructure.db.session import get_db

router = APIRouter(dependencies=[Depends(enforce_authenticated_rate_limit)])

ALLOWED_DOCUMENTS = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "text/markdown": ".md",
    "text/plain": ".txt",
}
DOCUMENT_TYPES = {"MANUAL", "SOP", "SAFETY"}


def _upload_root(request: Request) -> Path:
    root = Path(request.app.state.settings.upload_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _signature_matches(content_type: str, content: bytes) -> bool:
    if content_type == "application/pdf":
        return content.startswith(b"%PDF-")
    if content_type == "image/jpeg":
        return content.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type in {"text/markdown", "text/plain"}:
        return bool(content.strip())
    return content.startswith(b"RIFF") and content[8:12] == b"WEBP"


def _data(request: Request, document: DeviceDocument) -> DeviceDocumentData:
    asset = document.asset
    return DeviceDocumentData(
        id=document.id,
        device_id=document.device_id,
        document_type=document.document_type,  # type: ignore[arg-type]
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


async def _load_device_document(
    session: AsyncSession,
    token: str,
    principal: Principal,
) -> DeviceDocument:
    scope = college_scope(principal)
    conditions = [
        UploadAsset.asset_token == token,
        DeviceDocument.active.is_(True),
    ]
    if scope is not None:
        conditions.append(DeviceDocument.college_id == scope)
    document = await session.scalar(
        select(DeviceDocument)
        .join(UploadAsset, UploadAsset.id == DeviceDocument.asset_id)
        .options(selectinload(DeviceDocument.asset), selectinload(DeviceDocument.device))
        .where(*conditions)
    )
    if document is None:
        raise ApiError("DOCUMENT_NOT_FOUND", "文档不存在或无权访问", 404)
    return document


@router.get("/devices/{device_id}/documents", response_model=ApiResponse[list[DeviceDocumentData]])
async def list_device_documents(
    device_id: int,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[list[DeviceDocumentData]]:
    service = ReservationService(session, principal)
    await service._load_device(device_id)
    rows = list(
        (
            await session.scalars(
                select(DeviceDocument)
                .options(selectinload(DeviceDocument.asset))
                .where(DeviceDocument.device_id == device_id, DeviceDocument.active.is_(True))
                .order_by(DeviceDocument.document_type, DeviceDocument.id.desc())
            )
        ).all()
    )
    return ApiResponse.ok([_data(request, row) for row in rows])


@router.post(
    "/devices/{device_id}/documents",
    response_model=ApiResponse[DeviceDocumentData],
    status_code=201,
)
async def upload_device_document(
    device_id: int,
    request: Request,
    document_type: str = Form(...),
    title: str = Form(...),
    version: str = Form(default="1.0"),
    requires_ack: bool = Form(default=False),
    file: UploadFile = File(...),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[DeviceDocumentData]:
    if document_type not in DOCUMENT_TYPES:
        raise ApiError("DOCUMENT_TYPE_INVALID", "文档类型必须是设备手册或操作规程", 422)
    normalized_title = title.strip()
    if not 2 <= len(normalized_title) <= 200:
        raise ApiError("DOCUMENT_TITLE_INVALID", "文档标题长度必须为 2 到 200 个字符", 422)
    normalized_version = version.strip()
    if not 1 <= len(normalized_version) <= 40:
        raise ApiError("DOCUMENT_VERSION_INVALID", "文档版本不能为空且不能超过 40 个字符", 422)
    service = ReservationService(session, principal)
    device = await service._load_device(device_id)
    if not await service._can_manage_device(device):
        raise ApiError("FORBIDDEN", "只能管理自己负责范围内的设备文档", 403)

    content_type = (file.content_type or "").lower()
    suffix = ALLOWED_DOCUMENTS.get(content_type)
    if suffix is None:
        raise ApiError("DOCUMENT_TYPE_INVALID", "只支持 PDF、JPG、PNG、WebP 或 Markdown 文档", 422)
    max_bytes = int(request.app.state.settings.upload_max_bytes)
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ApiError("UPLOAD_TOO_LARGE", "文档大小不能超过 5 MB", 413)
    if not _signature_matches(content_type, content):
        raise ApiError("UPLOAD_CONTENT_INVALID", "文档内容与文件类型不匹配", 422)

    token = secrets.token_urlsafe(32)
    path = _upload_root(request) / f"{token}{suffix}"
    await asyncio.to_thread(path.write_bytes, content)
    original_name = Path(file.filename or "document").name
    original_name = original_name.replace("\r", "").replace("\n", "")[:255] or "document"
    asset = UploadAsset(
        asset_token=token,
        user_id=principal.user_id,
        college_id=device.college_id,
        original_name=original_name,
        content_type=content_type,
        size_bytes=len(content),
        storage_path=str(path),
    )
    document = DeviceDocument(
        device_id=device.id,
        college_id=device.college_id,
        document_type=document_type,
        title=normalized_title,
        version=normalized_version,
        requires_ack=requires_ack,
        created_by=principal.user_id,
        published_at=datetime.now(UTC).replace(tzinfo=None),
        asset=asset,
    )
    await session.execute(
        update(DeviceDocument)
        .where(
            DeviceDocument.device_id == device.id,
            DeviceDocument.document_type == document_type,
            DeviceDocument.active.is_(True),
        )
        .values(active=False)
    )
    session.add(document)
    try:
        await session.flush()
        append_audit(
            session,
            user_id=principal.user_id,
            college_id=device.college_id,
            action="DEVICE_DOCUMENT_CREATE",
            target_type="DEVICE_DOCUMENT",
            target_id=document.id,
            detail={"device_id": device.id, "document_type": document_type},
        )
        await session.commit()
        await session.refresh(document, attribute_names=["created_at"])
    except Exception:
        await session.rollback()
        await asyncio.to_thread(path.unlink, missing_ok=True)
        raise
    return ApiResponse.ok(_data(request, document))


@router.delete("/devices/{device_id}/documents/{document_id}", response_model=ApiResponse[None])
async def archive_device_document(
    device_id: int,
    document_id: int,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    service = ReservationService(session, principal)
    device = await service._load_device(device_id)
    if not await service._can_manage_device(device):
        raise ApiError("FORBIDDEN", "只能管理自己负责范围内的设备文档", 403)
    document = await session.scalar(
        select(DeviceDocument).where(
            DeviceDocument.id == document_id,
            DeviceDocument.device_id == device_id,
            DeviceDocument.active.is_(True),
        )
    )
    if document is None:
        raise ApiError("DOCUMENT_NOT_FOUND", "文档不存在或已归档", 404)
    document.active = False
    append_audit(
        session,
        user_id=principal.user_id,
        college_id=device.college_id,
        action="DEVICE_DOCUMENT_ARCHIVE",
        target_type="DEVICE_DOCUMENT",
        target_id=document.id,
        detail={"device_id": device.id},
    )
    await session.commit()
    return ApiResponse.ok(None)


@router.get("/device-documents/{asset_token}", include_in_schema=False)
async def download_device_document(
    asset_token: str,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> FileResponse:
    document = await _load_device_document(session, asset_token, principal)
    root = _upload_root(request)
    path = Path(document.asset.storage_path).resolve()
    if root not in path.parents or not path.is_file():
        raise ApiError("DOCUMENT_NOT_FOUND", "文档文件不存在", 404)
    return FileResponse(
        path,
        media_type=document.asset.content_type,
        filename=document.asset.original_name,
    )
