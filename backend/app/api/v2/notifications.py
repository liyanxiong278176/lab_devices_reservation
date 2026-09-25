from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import Principal, college_scope, get_current_principal
from app.common.response import ApiResponse
from app.core.errors import ApiError
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.db.models import Notification
from app.infrastructure.db.pagination import delayed_page_ids, page_metadata, page_offset
from app.infrastructure.db.session import get_db

router = APIRouter(dependencies=[Depends(enforce_authenticated_rate_limit)])


def _row(row: Notification) -> dict[str, object]:
    return {
        "id": row.id,
        "userId": row.user_id,
        "type": row.type,
        "title": row.title,
        "content": row.content,
        "relatedId": row.related_id,
        "relatedType": row.related_type,
        "isRead": 1 if row.is_read else 0,
        "createdAt": row.created_at,
    }


def _conditions(principal: Principal, only_unread: bool = False):
    values = [Notification.user_id == principal.user_id]
    scope = college_scope(principal)
    if scope is not None:
        values.append(Notification.college_id == scope)
    if only_unread:
        values.append(Notification.is_read.is_(False))
    return values


@router.get("/notifications/mine", response_model=ApiResponse[dict[str, object]])
async def my_notifications(
    only_unread: bool = Query(default=False, alias="onlyUnread"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=10, ge=1, le=100),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, object]]:
    page_offset(page, size)
    conditions = _conditions(principal, only_unread)
    total = int(await session.scalar(select(func.count(Notification.id)).where(*conditions)) or 0)
    page_ids = delayed_page_ids(
        select(Notification.id).where(*conditions),
        Notification.id,
        page=page,
        page_size=size,
    )
    rows = list(
        (
            await session.scalars(
                select(Notification)
                .join(page_ids, page_ids.c.id == Notification.id)
                .order_by(Notification.id.desc())
            )
        ).all()
    )
    pages, truncated = page_metadata(total, size)
    return ApiResponse.ok(
        {
            "records": [_row(row) for row in rows],
            "total": total,
            "size": size,
            "current": page,
            "pages": pages,
            "truncated": truncated,
        }
    )


@router.patch("/notifications/{notification_id}/read", response_model=ApiResponse[None])
async def mark_read(
    notification_id: int,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    result = await session.execute(
        update(Notification)
        .where(*_conditions(principal), Notification.id == notification_id)
        .values(is_read=True)
    )
    if result.rowcount != 1:
        raise ApiError("NOTIFICATION_NOT_FOUND", "通知不存在或无权操作", 404)
    await session.commit()
    return ApiResponse.ok(None)


@router.patch("/notifications/read-all", response_model=ApiResponse[None])
async def mark_all_read(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await session.execute(update(Notification).where(*_conditions(principal)).values(is_read=True))
    await session.commit()
    return ApiResponse.ok(None)
