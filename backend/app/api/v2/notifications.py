from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import Principal, college_scope, get_current_principal
from app.common.response import ApiResponse
from app.core.errors import ApiError
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.db.models import Notification
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
    cursor: int | None = Query(default=None, ge=1),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, object]]:
    conditions = _conditions(principal, only_unread)
    total = int(await session.scalar(select(func.count(Notification.id)).where(*conditions)) or 0)
    query_conditions = list(conditions)
    if cursor is not None:
        query_conditions.append(Notification.id < cursor)
    order_columns = (
        (Notification.id.desc(),)
        if cursor is not None
        else (Notification.created_at.desc(), Notification.id.desc())
    )
    rows = list(
        (
            await session.scalars(
                select(Notification)
                .where(*query_conditions)
                .order_by(*order_columns)
                .offset((page - 1) * size if cursor is None else 0)
                .limit(size + 1 if cursor is not None else size)
            )
        ).all()
    )
    has_more = cursor is not None and len(rows) > size
    if has_more:
        rows = rows[:size]
    return ApiResponse.ok(
        {
            "records": [_row(row) for row in rows],
            "total": total,
            "size": size,
            "current": page,
            "pages": (total + size - 1) // size if total else 0,
            "next_cursor": rows[-1].id if has_more and rows else None,
            "has_more": has_more,
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
