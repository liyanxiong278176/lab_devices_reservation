from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.security import Principal, college_scope, get_current_principal
from app.common.response import ApiResponse
from app.core.errors import ApiError
from app.infrastructure.cache.invalidation import (
    enqueue_catalog_cache_bump,
    sync_catalog_cache_bump,
)
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.db.models import College, DeviceCategory, Lab, User
from app.infrastructure.db.pagination import delayed_page_ids, page_metadata, page_offset
from app.infrastructure.db.session import get_db

router = APIRouter(dependencies=[Depends(enforce_authenticated_rate_limit)])


class LabData(BaseModel):
    id: int
    name: str
    college_id: int | None = None
    location: str | None = None
    manager_id: int | None = None
    manager_name: str | None = None
    college_name: str | None = None
    description: str | None = None
    status: int


class CollegeData(BaseModel):
    id: int
    code: str
    name: str
    manager_id: int | None = None
    manager_name: str | None = None


class ManagerData(BaseModel):
    id: int
    username: str
    real_name: str | None = None
    college_id: int


class CollegeWriteRequest(BaseModel):
    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=2, max_length=128)
    manager_id: int | None = Field(default=None, gt=0)


class LabWriteRequest(BaseModel):
    college_id: int = Field(gt=0)
    name: str = Field(min_length=2, max_length=100)
    location: str | None = Field(default=None, max_length=200)
    manager_id: int | None = Field(default=None, gt=0)
    description: str | None = Field(default=None, max_length=500)


class CategoryData(BaseModel):
    id: int
    name: str
    parent_id: int
    sort: int
    children: list[CategoryData] = Field(default_factory=list)


def _can_admin(principal: Principal) -> bool:
    return principal.is_system_admin or (
        principal.is_lab_admin and principal.has_permission("organization:read")
    )


def _require_system_admin(principal: Principal) -> None:
    if not principal.is_system_admin or not principal.has_permission("organization:manage"):
        raise ApiError("FORBIDDEN", "仅系统管理员可以配置学院和实验室", 403)


async def _active_college(session: AsyncSession, college_id: int) -> College:
    college = await session.scalar(
        select(College).where(College.id == college_id, College.status == 1)
    )
    if college is None:
        raise ApiError("COLLEGE_NOT_FOUND", "学院不存在或未启用", 422)
    return college


async def _resolve_manager(
    session: AsyncSession,
    manager_id: int | None,
    college_id: int,
) -> User | None:
    if manager_id is None:
        return None
    manager = await session.scalar(
        select(User)
        .options(selectinload(User.roles))
        .where(User.id == manager_id, User.status == 1)
    )
    if manager is None or manager.college_id != college_id:
        raise ApiError("MANAGER_INVALID", "负责人必须是当前学院的启用用户", 422)
    if not any(role.role_code in {"LAB_ADMIN", "SYS_ADMIN"} for role in manager.roles):
        raise ApiError("MANAGER_ROLE_REQUIRED", "负责人必须拥有实验室管理员角色", 422)
    return manager


def _college_rows_data(rows: list[College], manager_names: dict[int, str]) -> list[CollegeData]:
    return [
        CollegeData(
            id=row.id,
            code=row.code,
            name=row.name,
            manager_id=row.manager_id,
            manager_name=manager_names.get(row.manager_id or 0),
        )
        for row in rows
    ]


@router.get("/colleges", response_model=ApiResponse[list[CollegeData]])
async def list_colleges(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[list[CollegeData]]:
    if not _can_admin(principal):
        raise ApiError("FORBIDDEN", "当前角色无学院管理权限", 403)
    scope = college_scope(principal)
    stmt = select(College).where(College.status == 1).order_by(College.id)
    if scope is not None:
        stmt = stmt.where(College.id == scope)
    rows = list((await session.scalars(stmt)).all())
    manager_ids = {row.manager_id for row in rows if row.manager_id is not None}
    managers = (
        list((await session.scalars(select(User).where(User.id.in_(manager_ids)))).all())
        if manager_ids
        else []
    )
    manager_names = {manager.id: manager.real_name or manager.username for manager in managers}
    return ApiResponse.ok(_college_rows_data(rows, manager_names))


@router.get("/organization/managers", response_model=ApiResponse[list[ManagerData]])
async def list_managers(
    college_id: int = Query(gt=0),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[list[ManagerData]]:
    _require_system_admin(principal)
    await _active_college(session, college_id)
    users = list(
        (
            await session.scalars(
                select(User)
                .options(selectinload(User.roles))
                .where(User.college_id == college_id, User.status == 1)
                .order_by(User.id)
            )
        ).all()
    )
    return ApiResponse.ok(
        [
            ManagerData(
                id=user.id,
                username=user.username,
                real_name=user.real_name,
                college_id=college_id,
            )
            for user in users
            if any(role.role_code in {"LAB_ADMIN", "SYS_ADMIN"} for role in user.roles)
        ]
    )


@router.post("/colleges", response_model=ApiResponse[CollegeData], status_code=201)
async def create_college(
    payload: CollegeWriteRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[CollegeData]:
    _require_system_admin(principal)
    code = payload.code.strip().upper()
    name = payload.name.strip()
    if await session.scalar(select(College).where(or_(College.code == code, College.name == name))):
        raise ApiError("COLLEGE_EXISTS", "学院编码或名称已存在", 409)
    college = College(code=code, name=name, status=1)
    session.add(college)
    await session.flush()
    manager = await _resolve_manager(session, payload.manager_id, college.id)
    college.manager_id = manager.id if manager else None
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError("COLLEGE_EXISTS", "学院编码或名称已存在", 409) from exc
    return ApiResponse.ok(
        CollegeData(
            id=college.id,
            code=college.code,
            name=college.name,
            manager_id=college.manager_id,
            manager_name=manager.real_name or manager.username if manager else None,
        )
    )


@router.put("/colleges/{college_id}", response_model=ApiResponse[CollegeData])
async def update_college(
    college_id: int,
    payload: CollegeWriteRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[CollegeData]:
    _require_system_admin(principal)
    college = await _active_college(session, college_id)
    code = payload.code.strip().upper()
    name = payload.name.strip()
    duplicate = await session.scalar(
        select(College).where(
            College.id != college_id,
            or_(College.code == code, College.name == name),
        )
    )
    if duplicate is not None:
        raise ApiError("COLLEGE_EXISTS", "学院编码或名称已存在", 409)
    manager = await _resolve_manager(session, payload.manager_id, college_id)
    college.code = code
    college.name = name
    college.manager_id = manager.id if manager else None
    enqueue_catalog_cache_bump(session, college_id)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError("COLLEGE_EXISTS", "学院编码或名称已存在", 409) from exc
    await sync_catalog_cache_bump(request.app, college_id)
    return ApiResponse.ok(
        CollegeData(
            id=college.id,
            code=college.code,
            name=college.name,
            manager_id=college.manager_id,
            manager_name=manager.real_name or manager.username if manager else None,
        )
    )


@router.get("/labs", response_model=ApiResponse[dict[str, object]])
async def list_labs(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=100, ge=1, le=200),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, object]]:
    if not _can_admin(principal):
        raise ApiError("FORBIDDEN", "当前角色无实验室管理权限", 403)
    page_offset(page, size)
    scope = college_scope(principal)
    conditions = [Lab.status == 1]
    if scope is not None:
        conditions.extend(
            [
                Lab.college_id == scope,
                or_(
                    Lab.manager_id == principal.user_id,
                    College.manager_id == principal.user_id,
                ),
            ]
        )
    id_stmt = select(Lab.id).where(*conditions)
    count_stmt = select(func.count(Lab.id)).select_from(Lab).where(*conditions)
    if scope is not None:
        id_stmt = id_stmt.join(College, College.id == Lab.college_id)
        count_stmt = count_stmt.join(College, College.id == Lab.college_id)
    total = int(await session.scalar(count_stmt) or 0)
    page_ids = delayed_page_ids(
        id_stmt,
        Lab.id,
        page=page,
        page_size=size,
    )
    labs = list(
        (
            await session.scalars(
                select(Lab)
                .join(page_ids, page_ids.c.id == Lab.id)
                .options(selectinload(Lab.manager), selectinload(Lab.college))
                .order_by(Lab.id.desc())
            )
        ).all()
    )
    pages, truncated = page_metadata(total, size)
    records = [
        LabData(
            id=lab.id,
            name=lab.name,
            college_id=lab.college_id,
            location=lab.location,
            manager_id=lab.manager_id,
            manager_name=(lab.manager.real_name or lab.manager.username) if lab.manager else None,
            college_name=lab.college.name if lab.college else None,
            description=lab.description,
            status=lab.status,
        )
        for lab in labs
    ]
    return ApiResponse.ok(
        {
            "records": records,
            "total": total,
            "size": size,
            "current": page,
            "pages": pages,
            "truncated": truncated,
        }
    )


@router.post("/labs", response_model=ApiResponse[LabData], status_code=201)
async def create_lab(
    payload: LabWriteRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[LabData]:
    _require_system_admin(principal)
    college = await _active_college(session, payload.college_id)
    manager = await _resolve_manager(session, payload.manager_id, college.id)
    lab = Lab(
        college_id=college.id,
        name=payload.name.strip(),
        location=(payload.location or "").strip() or None,
        manager_id=manager.id if manager else None,
        description=(payload.description or "").strip() or None,
        status=1,
    )
    session.add(lab)
    enqueue_catalog_cache_bump(session, college.id)
    await session.commit()
    await session.refresh(lab)
    await sync_catalog_cache_bump(request.app, college.id)
    return ApiResponse.ok(
        LabData(
            id=lab.id,
            name=lab.name,
            college_id=lab.college_id,
            location=lab.location,
            manager_id=lab.manager_id,
            manager_name=(manager.real_name or manager.username) if manager else None,
            college_name=college.name,
            description=lab.description,
            status=lab.status,
        )
    )


@router.put("/labs/{lab_id}", response_model=ApiResponse[LabData])
async def update_lab(
    lab_id: int,
    payload: LabWriteRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[LabData]:
    _require_system_admin(principal)
    lab = await session.scalar(
        select(Lab).options(selectinload(Lab.college)).where(Lab.id == lab_id, Lab.status == 1)
    )
    if lab is None:
        raise ApiError("LAB_NOT_FOUND", "实验室不存在或未启用", 404)
    if lab.college_id != payload.college_id:
        raise ApiError("LAB_COLLEGE_IMMUTABLE", "实验室所属学院不能直接变更", 409)
    college = await _active_college(session, lab.college_id)
    manager = await _resolve_manager(session, payload.manager_id, college.id)
    lab.name = payload.name.strip()
    lab.location = (payload.location or "").strip() or None
    lab.manager_id = manager.id if manager else None
    lab.description = (payload.description or "").strip() or None
    enqueue_catalog_cache_bump(session, college.id)
    await session.commit()
    await sync_catalog_cache_bump(request.app, college.id)
    return ApiResponse.ok(
        LabData(
            id=lab.id,
            name=lab.name,
            college_id=lab.college_id,
            location=lab.location,
            manager_id=lab.manager_id,
            manager_name=(manager.real_name or manager.username) if manager else None,
            college_name=college.name,
            description=lab.description,
            status=lab.status,
        )
    )


@router.get("/device-categories", response_model=ApiResponse[list[CategoryData]])
async def category_tree(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[list[CategoryData]]:
    # Categories are global reference data; access still requires an authenticated user.
    del principal
    rows = list(
        (
            await session.scalars(
                select(DeviceCategory).order_by(DeviceCategory.sort, DeviceCategory.id)
            )
        ).all()
    )
    nodes = {
        row.id: CategoryData(
            id=row.id,
            name=row.name,
            parent_id=row.parent_id,
            sort=row.sort,
        )
        for row in rows
    }
    roots: list[CategoryData] = []
    for row in rows:
        node = nodes[row.id]
        parent = nodes.get(row.parent_id)
        if parent is None or row.parent_id == 0:
            roots.append(node)
        else:
            parent.children.append(node)
    return ApiResponse.ok(roots)
