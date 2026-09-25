"""Upload storage quotas and conservative cleanup of abandoned assets."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Request
from sqlalchemy import String, cast, collate, func, or_, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.infrastructure.db.models import (
    DeviceDocument,
    DeviceHandover,
    DeviceQualification,
    KnowledgeDocument,
    RepairReport,
    RepairWorklog,
    ReservationInspection,
    UploadAsset,
    UploadQuotaBucket,
)

logger = logging.getLogger(__name__)


def _contains_upload_token(value: object, token: object, *, mysql: bool):
    """Search serialized URLs with a stable collation on MySQL JSON casts."""
    searchable_value = cast(value, String)
    searchable_token = token
    if mysql:
        searchable_value = collate(searchable_value, "utf8mb4_bin")
        searchable_token = collate(searchable_token, "utf8mb4_bin")
    return searchable_value.contains(searchable_token)


def _upload_is_referenced(
    asset_id: object,
    asset_token: object,
    storage_path: object | None = None,
    *,
    mysql: bool,
):
    """Build a correlated predicate for every business-owned upload reference."""
    references = [
        select(DeviceDocument.id).where(DeviceDocument.asset_id == asset_id).exists(),
        select(DeviceQualification.id).where(DeviceQualification.asset_id == asset_id).exists(),
        select(DeviceHandover.id)
        .where(
            or_(
                _contains_upload_token(
                    DeviceHandover.handover_image_urls, asset_token, mysql=mysql
                ),
                _contains_upload_token(DeviceHandover.return_image_urls, asset_token, mysql=mysql),
            )
        )
        .exists(),
        select(RepairReport.id)
        .where(_contains_upload_token(RepairReport.image_urls, asset_token, mysql=mysql))
        .exists(),
        select(RepairWorklog.id)
        .where(_contains_upload_token(RepairWorklog.image_urls, asset_token, mysql=mysql))
        .exists(),
        select(ReservationInspection.id)
        .where(_contains_upload_token(ReservationInspection.image_urls, asset_token, mysql=mysql))
        .exists(),
    ]
    if storage_path is not None:
        references.append(
            select(KnowledgeDocument.id)
            .where(KnowledgeDocument.source_file_path == storage_path)
            .exists()
        )
    return or_(*references)


def _quota_scopes(user_id: int, college_id: int | None) -> list[tuple[str, int]]:
    scopes = [("global", 0)]
    if college_id is not None:
        scopes.append(("college", college_id))
    scopes.append(("user", user_id))
    return scopes


async def _existing_scope_usage(
    session: AsyncSession,
    scope_type: str,
    scope_id: int,
) -> int:
    statement = select(func.coalesce(func.sum(UploadAsset.size_bytes), 0))
    if scope_type == "college":
        statement = statement.where(UploadAsset.college_id == scope_id)
    elif scope_type == "user":
        statement = statement.where(UploadAsset.user_id == scope_id)
    return int(await session.scalar(statement) or 0)


async def _ensure_upload_quota_bucket(
    session: AsyncSession,
    scope_type: str,
    scope_id: int,
) -> None:
    initial_usage = await _existing_scope_usage(session, scope_type, scope_id)
    values = {"scope_type": scope_type, "scope_id": scope_id, "used_bytes": initial_usage}
    dialect = session.get_bind().dialect.name
    if dialect == "mysql":
        statement = (
            mysql_insert(UploadQuotaBucket)
            .values(**values)
            .on_duplicate_key_update(scope_type=scope_type)
        )
    elif dialect == "sqlite":
        statement = (
            sqlite_insert(UploadQuotaBucket)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["scope_type", "scope_id"])
        )
    else:
        existing = await session.scalar(
            select(UploadQuotaBucket.id).where(
                UploadQuotaBucket.scope_type == scope_type,
                UploadQuotaBucket.scope_id == scope_id,
            )
        )
        if existing is None:
            session.add(UploadQuotaBucket(**values))
            await session.flush()
        return
    await session.execute(statement)


async def _lock_upload_quota_buckets(
    session: AsyncSession,
    scopes: list[tuple[str, int]],
) -> dict[tuple[str, int], UploadQuotaBucket]:
    for scope_type, scope_id in scopes:
        await _ensure_upload_quota_bucket(session, scope_type, scope_id)
    buckets: dict[tuple[str, int], UploadQuotaBucket] = {}
    for scope_type, scope_id in scopes:
        bucket = await session.scalar(
            select(UploadQuotaBucket)
            .where(
                UploadQuotaBucket.scope_type == scope_type,
                UploadQuotaBucket.scope_id == scope_id,
            )
            .with_for_update()
        )
        if bucket is None:
            raise ApiError("UPLOAD_QUOTA_UNAVAILABLE", "附件配额暂不可用，请重试", 503)
        buckets[(scope_type, scope_id)] = bucket
    return buckets


async def _ai_knowledge_storage_usage(
    session: AsyncSession,
    *,
    upload_dir: str,
    college_id: int | None = None,
) -> int:
    statement = select(KnowledgeDocument.source_file_path).where(
        KnowledgeDocument.source_file_path.is_not(None)
    )
    if college_id is not None:
        statement = statement.where(KnowledgeDocument.college_id == college_id)
    paths = [str(value) for value in (await session.scalars(statement)).all() if value]
    root = (Path(upload_dir).resolve() / "ai-knowledge").resolve()

    def total_size() -> int:
        total = 0
        for raw_path in paths:
            path = Path(raw_path).resolve()
            if root not in path.parents:
                continue
            try:
                total += path.stat().st_size
            except OSError:
                continue
        return total

    return await asyncio.to_thread(total_size)


@asynccontextmanager
async def upload_quota_guard(
    request: Request,
    session: AsyncSession,
    *,
    user_id: int,
    college_id: int | None = None,
    incoming_bytes: int,
    ai_knowledge_document: bool = False,
) -> AsyncIterator[None]:
    """Atomically reserve user, college and global storage within the DB transaction."""
    app: FastAPI = request.app
    lock: asyncio.Lock = getattr(app.state, "upload_quota_lock", asyncio.Lock())
    app.state.upload_quota_lock = lock
    async with lock:
        scopes = _quota_scopes(user_id, college_id)
        buckets = await _lock_upload_quota_buckets(session, scopes)
        settings = app.state.settings
        caps = {
            "global": settings.upload_total_quota_bytes,
            "college": settings.upload_college_quota_bytes,
            "user": settings.upload_user_quota_bytes,
        }
        errors = {
            "global": (
                "UPLOAD_STORAGE_FULL",
                "系统附件存储空间暂时不足，请稍后重试或联系管理员",
                507,
            ),
            "college": (
                "UPLOAD_COLLEGE_QUOTA_EXCEEDED",
                "本学院附件存储空间已满，请联系管理员扩容",
                413,
            ),
            "user": (
                "UPLOAD_USER_QUOTA_EXCEEDED",
                "个人附件存储空间已满，请联系管理员清理或扩容",
                413,
            ),
        }
        # Check user then tenant then global for the most actionable error;
        # rows themselves were acquired in the stable global/college/user order.
        for scope_type in ("user", "college", "global"):
            scope = next((item for item in scopes if item[0] == scope_type), None)
            if scope is None:
                continue
            bucket = buckets[scope]
            if bucket.used_bytes + incoming_bytes > caps[scope_type]:
                code, message, status = errors[scope_type]
                raise ApiError(
                    code,
                    message,
                    status,
                    data={"used_bytes": bucket.used_bytes, "quota_bytes": caps[scope_type]},
                )
        if ai_knowledge_document:
            settings = app.state.settings
            global_ai_used = await _ai_knowledge_storage_usage(
                session,
                upload_dir=settings.upload_dir,
            )
            if global_ai_used + incoming_bytes > settings.ai_knowledge_global_storage_bytes:
                raise ApiError(
                    "AI_KNOWLEDGE_STORAGE_FULL",
                    "全校知识库原件存储空间已满",
                    507,
                    data={
                        "used_bytes": global_ai_used,
                        "quota_bytes": settings.ai_knowledge_global_storage_bytes,
                    },
                )
            if college_id is not None:
                college_ai_used = await _ai_knowledge_storage_usage(
                    session,
                    upload_dir=settings.upload_dir,
                    college_id=college_id,
                )
                if college_ai_used + incoming_bytes > settings.ai_knowledge_college_storage_bytes:
                    raise ApiError(
                        "AI_KNOWLEDGE_COLLEGE_QUOTA_EXCEEDED",
                        "本学院知识库原件存储空间已满",
                        413,
                        data={
                            "used_bytes": college_ai_used,
                            "quota_bytes": settings.ai_knowledge_college_storage_bytes,
                        },
                    )
        for bucket in buckets.values():
            bucket.used_bytes += incoming_bytes
        await session.flush()
        yield


async def cleanup_orphan_uploads(
    session: AsyncSession,
    upload_dir: str,
    *,
    retention_hours: int = 24,
    batch_size: int = 100,
) -> int:
    """Remove old uploaded assets not referenced by business records.

    Device manuals and qualifications use foreign keys; repair/return evidence
    stores private upload URLs in JSON arrays, so those references are checked
    before deleting anything.
    """
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=retention_hours)
    mysql = session.get_bind().dialect.name == "mysql"
    assets = list(
        (
            await session.scalars(
                select(UploadAsset)
                .where(
                    UploadAsset.created_at < cutoff,
                    ~_upload_is_referenced(
                        UploadAsset.id,
                        UploadAsset.asset_token,
                        UploadAsset.storage_path,
                        mysql=mysql,
                    ),
                )
                .order_by(UploadAsset.id)
                .limit(batch_size)
            )
        ).all()
    )
    root = Path(upload_dir).resolve()
    removed = 0
    for candidate in assets:
        asset = await session.scalar(
            select(UploadAsset)
            .where(UploadAsset.id == candidate.id)
            .with_for_update(skip_locked=True)
        )
        if asset is None:
            continue
        # Recheck after candidate selection to avoid deleting an asset that
        # acquired a business reference while the cleanup batch was loading.
        # Evidence writers lock the same asset rows before recording JSON URLs.
        is_referenced = await session.scalar(
            select(
                _upload_is_referenced(
                    asset.id,
                    asset.asset_token,
                    asset.storage_path,
                    mysql=mysql,
                )
            )
        )
        if is_referenced:
            continue
        path = Path(asset.storage_path).resolve()
        if root not in path.parents:
            logger.warning("skip orphan upload outside configured directory: asset_id=%s", asset.id)
            continue
        try:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        except OSError:
            logger.exception("failed to remove orphan upload: asset_id=%s", asset.id)
            continue
        scopes = _quota_scopes(asset.user_id, asset.college_id)
        buckets = await _lock_upload_quota_buckets(session, scopes)
        for bucket in buckets.values():
            bucket.used_bytes = max(0, bucket.used_bytes - asset.size_bytes)
        await session.delete(asset)
        removed += 1
    if removed:
        await session.commit()
    return removed


async def upload_cleanup_loop(app: FastAPI) -> None:
    """Periodic janitor; stored business evidence is never removed."""
    interval = max(60, int(app.state.settings.upload_cleanup_interval_seconds))
    while True:
        try:
            factory = getattr(app.state, "session_factory", None)
            if factory is not None:
                async with factory() as session:
                    await cleanup_orphan_uploads(
                        session,
                        app.state.settings.upload_dir,
                        retention_hours=app.state.settings.upload_orphan_retention_hours,
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("periodic orphan upload cleanup failed")
        await asyncio.sleep(interval)
