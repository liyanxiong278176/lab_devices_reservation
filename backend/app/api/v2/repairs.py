import asyncio
import secrets
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v2.schemas import RepairData, RepairPage
from app.application.repairs import RepairService
from app.auth.security import Principal, college_scope, get_current_principal
from app.common.response import ApiResponse
from app.core.errors import ApiError
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.db.models import UploadAsset
from app.infrastructure.db.session import get_db

router = APIRouter(dependencies=[Depends(enforce_authenticated_rate_limit)])


class RepairCreateRequest(BaseModel):
    device_id: int = Field(gt=0)
    title: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    image_urls: list[str] | None = Field(default=None, max_length=6)
    priority: str = Field(default="NORMAL", pattern="^(NORMAL|IMPORTANT|URGENT)$")

    @field_validator("image_urls")
    @classmethod
    def validate_image_urls(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        for item in value:
            item = item.strip()
            parsed = urlparse(item)
            if (
                not item
                or len(item) > 500
                or (
                    parsed.scheme not in {"https"}
                    and not item.startswith("/uploads/")
                    and not item.startswith("/api/v2/repair-uploads/")
                )
            ):
                raise ValueError("图片地址必须是 HTTPS 或系统上传路径")
            normalized.append(item)
        return normalized


class RepairHandleRequest(BaseModel):
    resolution_note: str = Field(min_length=2, max_length=1000)


class UploadData(BaseModel):
    url: str
    name: str
    content_type: str
    size_bytes: int


ALLOWED_UPLOADS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def _matches_image_signature(content_type: str, content: bytes) -> bool:
    return (
        (content_type == "image/jpeg" and content.startswith(b"\xff\xd8\xff"))
        or (content_type == "image/png" and content.startswith(b"\x89PNG\r\n\x1a\n"))
        or (
            content_type == "image/webp"
            and content.startswith(b"RIFF")
            and content[8:12] == b"WEBP"
        )
    )


def _upload_root(request: Request) -> Path:
    root = Path(request.app.state.settings.upload_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


@router.post("/repair-uploads", response_model=ApiResponse[UploadData], status_code=201)
async def upload_repair_image(
    request: Request,
    file: UploadFile = File(...),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[UploadData]:
    content_type = (file.content_type or "").lower()
    suffix = ALLOWED_UPLOADS.get(content_type)
    if suffix is None:
        raise ApiError("UPLOAD_TYPE_INVALID", "只支持 JPG、PNG 或 WebP 图片", 422)
    max_bytes = int(request.app.state.settings.upload_max_bytes)
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ApiError("UPLOAD_TOO_LARGE", "图片大小不能超过 5 MB", 413)
    if not _matches_image_signature(content_type, content):
        raise ApiError("UPLOAD_CONTENT_INVALID", "图片内容与文件类型不匹配", 422)
    token = secrets.token_urlsafe(32)
    path = _upload_root(request) / f"{token}{suffix}"
    await asyncio.to_thread(path.write_bytes, content)
    original_name = Path(file.filename or "attachment").name
    original_name = original_name.replace("\r", "").replace("\n", "")[:255] or "attachment"
    asset = UploadAsset(
        asset_token=token,
        user_id=principal.user_id,
        college_id=college_scope(principal),
        original_name=original_name,
        content_type=content_type,
        size_bytes=len(content),
        storage_path=str(path),
    )
    session.add(asset)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        await asyncio.to_thread(path.unlink, missing_ok=True)
        raise
    return ApiResponse.ok(
        UploadData(
            url=f"/api/v2/repair-uploads/{token}",
            name=asset.original_name,
            content_type=asset.content_type,
            size_bytes=asset.size_bytes,
        )
    )


@router.get("/repair-uploads/{asset_token}", include_in_schema=False)
async def get_repair_image(
    asset_token: str,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> FileResponse:
    asset = await session.scalar(select(UploadAsset).where(UploadAsset.asset_token == asset_token))
    scope = college_scope(principal)
    if asset is None or (scope is not None and asset.college_id != scope):
        raise ApiError("UPLOAD_NOT_FOUND", "图片不存在或无权访问", 404)
    root = _upload_root(request)
    path = Path(asset.storage_path).resolve()
    if root not in path.parents or not path.is_file():
        raise ApiError("UPLOAD_NOT_FOUND", "图片文件不存在", 404)
    return FileResponse(path, media_type=asset.content_type, filename=asset.original_name)


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
            priority=payload.priority,
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


class RepairConfirmRequest(BaseModel):
    confirmed: bool
    note: str | None = Field(default=None, max_length=500)


@router.post("/repair-reports/{report_id}/confirm", response_model=ApiResponse[RepairData])
async def confirm_repair(
    report_id: int,
    payload: RepairConfirmRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[RepairData]:
    return ApiResponse.ok(
        await RepairService(session, principal, request.app).confirm(
            report_id,
            confirmed=payload.confirmed,
            note=payload.note,
        )
    )


@router.get(
    "/repair-reports/{report_id}/worklogs",
    response_model=ApiResponse[list[dict[str, object]]],
)
async def repair_worklogs(
    report_id: int,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[list[dict[str, object]]]:
    return ApiResponse.ok(await RepairService(session, principal, request.app).worklogs(report_id))
