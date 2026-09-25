from typing import Any

from sqlalchemy.sql import ColumnElement, Select
from sqlalchemy.sql.selectable import Subquery

from app.core.errors import ApiError

MAX_PAGE_SKIP = 100_000


def page_offset(page: int, page_size: int) -> int:
    """Return a bounded OFFSET for a stable page-number query."""

    offset = (page - 1) * page_size
    if offset > MAX_PAGE_SKIP:
        raise ApiError(
            "PAGE_DEPTH_EXCEEDED",
            f"深页最多支持跳过 {MAX_PAGE_SKIP:,} 条匹配记录，请增加筛选条件后重试",
            422,
        )
    return offset


def page_metadata(total: int, page_size: int) -> tuple[int, bool]:
    """Return reachable page count and whether the 100k skip cap truncates it."""

    actual_pages = (total + page_size - 1) // page_size
    max_reachable_pages = MAX_PAGE_SKIP // page_size + 1
    return min(actual_pages, max_reachable_pages), actual_pages > max_reachable_pages


def delayed_page_ids(
    query: Select[tuple[Any]],
    id_column: ColumnElement[Any],
    *,
    page: int,
    page_size: int,
    name: str = "page_ids",
) -> Subquery:
    """Page only indexed IDs first; callers join this derived table for full rows."""

    return (
        query.order_by(id_column.desc())
        .offset(page_offset(page, page_size))
        .limit(page_size)
        .subquery(name)
    )
