from __future__ import annotations

import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.application.lifecycle import append_audit
from app.auth.rbac import bump_authz_version
from app.auth.security import Principal, get_current_principal
from app.common.response import ApiResponse
from app.core.errors import ApiError
from app.infrastructure.db.models import Permission, Role, User
from app.infrastructure.db.session import get_db

_SYSTEM_ONLY_PERMISSIONS = {"rbac:manage", "user:manage", "organization:manage"}


async def _require_rbac_admin(
    principal: Principal = Depends(get_current_principal),
) -> Principal:
    if not principal.is_system_admin or not principal.has_permission("rbac:manage"):
        raise ApiError("FORBIDDEN", "仅系统管理员可以管理角色权限", 403)
    return principal


router = APIRouter(dependencies=[Depends(_require_rbac_admin)])
_ROLE_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,49}$")


class RoleCreate(BaseModel):
    role_code: str = Field(min_length=2, max_length=50)
    role_name: str = Field(min_length=1, max_length=50)
    permission_codes: list[str] = Field(default_factory=list, max_length=100)


class RoleRename(BaseModel):
    role_name: str = Field(min_length=1, max_length=50)


class RolePermissionUpdate(BaseModel):
    permission_codes: list[str] = Field(max_length=100)


def _permission_data(permission: Permission) -> dict[str, str | None]:
    return {
        "code": permission.permission_code,
        "name": permission.permission_name,
        "module": permission.module,
        "description": permission.description,
    }


def _role_data(role: Role) -> dict[str, object]:
    return {
        "id": role.id,
        "code": role.role_code,
        "name": role.role_name,
        "is_system": role.is_system,
        "permissions": sorted(permission.permission_code for permission in role.permissions),
    }


async def _permissions_by_codes(session: AsyncSession, codes: list[str]) -> list[Permission]:
    normalized = list(dict.fromkeys(code.strip() for code in codes))
    if len(normalized) != len(codes):
        raise ApiError("DUPLICATE_PERMISSION", "权限列表不能包含重复项", 422)
    reserved = _SYSTEM_ONLY_PERMISSIONS.intersection(normalized)
    if reserved:
        raise ApiError(
            "SYSTEM_PERMISSION_RESERVED",
            f"系统专属权限不可分配给自定义角色: {', '.join(sorted(reserved))}",
            409,
        )
    rows = (
        list(
            (
                await session.scalars(
                    select(Permission).where(Permission.permission_code.in_(normalized))
                )
            ).all()
        )
        if normalized
        else []
    )
    found = {row.permission_code for row in rows}
    unknown = set(normalized) - found
    if unknown:
        raise ApiError(
            "PERMISSION_NOT_FOUND",
            f"权限不存在: {', '.join(sorted(unknown))}",
            422,
        )
    return rows


@router.get("/permissions", response_model=ApiResponse[list[dict[str, str | None]]])
async def list_permissions(
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[list[dict[str, str | None]]]:
    rows = list(
        (await session.scalars(select(Permission).order_by(Permission.module, Permission.id))).all()
    )
    return ApiResponse.ok([_permission_data(item) for item in rows])


@router.get("/roles", response_model=ApiResponse[list[dict[str, object]]])
async def list_roles(
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[list[dict[str, object]]]:
    rows = list(
        (
            await session.scalars(
                select(Role).options(selectinload(Role.permissions)).order_by(Role.id)
            )
        ).all()
    )
    return ApiResponse.ok([_role_data(item) for item in rows])


@router.post("/roles", response_model=ApiResponse[dict[str, object]], status_code=201)
async def create_role(
    payload: RoleCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, object]]:
    role_code = payload.role_code.strip().upper()
    if not _ROLE_CODE_PATTERN.fullmatch(role_code):
        raise ApiError("ROLE_CODE_INVALID", "角色代码只能由大写字母、数字和下划线组成", 422)
    if await session.scalar(select(Role.id).where(Role.role_code == role_code)) is not None:
        raise ApiError("ROLE_EXISTS", "角色代码已存在", 409)
    permissions = await _permissions_by_codes(session, payload.permission_codes)
    role = Role(
        role_code=role_code,
        role_name=payload.role_name.strip(),
        is_system=False,
        permissions=permissions,
    )
    session.add(role)
    await session.flush()
    await bump_authz_version(session)
    append_audit(
        session,
        user_id=principal.user_id,
        college_id=None,
        action="RBAC_ROLE_CREATE",
        target_type="ROLE",
        target_id=role.id,
        detail={"role_code": role_code, "permissions": sorted(payload.permission_codes)},
    )
    await session.commit()
    role = await session.scalar(
        select(Role).options(selectinload(Role.permissions)).where(Role.id == role.id)
    )
    assert role is not None
    return ApiResponse.ok(_role_data(role))


@router.patch("/roles/{role_id}", response_model=ApiResponse[dict[str, object]])
async def rename_role(
    role_id: int,
    payload: RoleRename,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, object]]:
    role = await session.scalar(
        select(Role).options(selectinload(Role.permissions)).where(Role.id == role_id)
    )
    if role is None:
        raise ApiError("ROLE_NOT_FOUND", "角色不存在", 404)
    if role.is_system:
        raise ApiError("SYSTEM_ROLE_PROTECTED", "系统角色名称不可修改", 409)
    role.role_name = payload.role_name.strip()
    append_audit(
        session,
        user_id=principal.user_id,
        college_id=None,
        action="RBAC_ROLE_RENAME",
        target_type="ROLE",
        target_id=role.id,
        detail={"role_code": role.role_code, "role_name": role.role_name},
    )
    await session.commit()
    return ApiResponse.ok(_role_data(role))


@router.put("/roles/{role_id}/permissions", response_model=ApiResponse[dict[str, object]])
async def update_role_permissions(
    role_id: int,
    payload: RolePermissionUpdate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, object]]:
    role = await session.scalar(
        select(Role).options(selectinload(Role.permissions)).where(Role.id == role_id)
    )
    if role is None:
        raise ApiError("ROLE_NOT_FOUND", "角色不存在", 404)
    if role.role_code == "SYS_ADMIN":
        raise ApiError("SYSTEM_ROLE_PROTECTED", "系统管理员角色权限不可修改", 409)
    permissions = await _permissions_by_codes(session, payload.permission_codes)
    role.permissions = permissions
    await bump_authz_version(session)
    append_audit(
        session,
        user_id=principal.user_id,
        college_id=None,
        action="RBAC_ROLE_PERMISSIONS_UPDATE",
        target_type="ROLE",
        target_id=role.id,
        detail={"role_code": role.role_code, "permissions": sorted(payload.permission_codes)},
    )
    await session.commit()
    await session.refresh(role, attribute_names=["permissions"])
    return ApiResponse.ok(_role_data(role))


@router.delete("/roles/{role_id}", response_model=ApiResponse[None])
async def delete_role(
    role_id: int,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    role = await session.scalar(select(Role).where(Role.id == role_id))
    if role is None:
        raise ApiError("ROLE_NOT_FOUND", "角色不存在", 404)
    if role.is_system:
        raise ApiError("SYSTEM_ROLE_PROTECTED", "系统角色不可删除", 409)
    if await session.scalar(select(func.count(User.id)).join(User.roles).where(Role.id == role.id)):
        raise ApiError("ROLE_IN_USE", "该角色仍分配给用户，不能删除", 409)
    role_code = role.role_code
    role_id = role.id
    await session.delete(role)
    await bump_authz_version(session)
    append_audit(
        session,
        user_id=principal.user_id,
        college_id=None,
        action="RBAC_ROLE_DELETE",
        target_type="ROLE",
        target_id=role_id,
        detail={"role_code": role_code},
    )
    await session.commit()
    return ApiResponse.ok(None)
