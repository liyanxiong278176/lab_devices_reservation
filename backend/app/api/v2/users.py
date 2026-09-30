from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.application.lifecycle import append_audit
from app.auth.rbac import bump_authz_version, lock_authz_version
from app.auth.security import Principal, get_current_principal, hash_password
from app.auth.sessions import SessionStoreUnavailable, revoke_user_sessions
from app.common.response import ApiResponse
from app.core.errors import ApiError
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.db.models import College, Role, User, user_roles
from app.infrastructure.db.pagination import delayed_page_ids, page_metadata, page_offset
from app.infrastructure.db.session import get_db

router = APIRouter(dependencies=[Depends(enforce_authenticated_rate_limit)])


class UserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str | None = Field(default=None, min_length=6, max_length=128)
    real_name: str | None = Field(default=None, max_length=50)
    phone: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=100)
    user_type: str = Field(default="STUDENT", max_length=20)
    role_codes: list[str] = Field(default_factory=list, max_length=5)
    college_id: int | None = Field(default=None, gt=0)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 3:
            raise ValueError("用户名至少需要 3 个字符")
        return normalized


def _require_admin(principal: Principal) -> None:
    if not principal.is_system_admin or not principal.has_permission("user:manage"):
        raise ApiError("FORBIDDEN", "仅系统管理员可以管理用户", 403)


def _data(user: User) -> dict[str, object]:
    return {
        "id": user.id,
        "username": user.username,
        "real_name": user.real_name,
        "phone": user.phone,
        "email": user.email,
        "user_type": user.user_type,
        "college_id": user.college_id,
        "status": user.status,
        "roles": [role.role_code for role in user.roles],
        "created_at": user.created_at,
    }


async def _resolve_college(
    session: AsyncSession,
    payload_college_id: int | None,
    principal: Principal,
    *,
    allow_global: bool = False,
) -> int | None:
    if payload_college_id is None and allow_global:
        return None
    college_id = payload_college_id or principal.college_id
    if college_id is not None:
        college = await session.scalar(
            select(College).where(College.id == college_id, College.status == 1)
        )
        if college is None:
            raise ApiError("COLLEGE_NOT_FOUND", "学院不存在或未启用", 422)
        return college.id
    colleges = list((await session.scalars(select(College).where(College.status == 1))).all())
    if len(colleges) == 1:
        return colleges[0].id
    raise ApiError("COLLEGE_REQUIRED", "创建业务用户时必须指定学院", 422)


async def _roles(session: AsyncSession, codes: list[str]) -> list[Role]:
    if not codes:
        return []
    if len(codes) != len(set(codes)):
        raise ApiError("DUPLICATE_ROLE", "角色列表不能包含重复项", 422)
    rows = list((await session.scalars(select(Role).where(Role.role_code.in_(codes)))).all())
    missing = set(codes) - {row.role_code for row in rows}
    if missing:
        raise ApiError("ROLE_NOT_FOUND", f"角色不存在: {', '.join(sorted(missing))}", 422)
    return rows


async def _protect_last_system_admin(
    session: AsyncSession,
    user: User,
    next_status: int,
    next_roles: list[Role] | None = None,
) -> None:
    current_is_admin = any(role.role_code == "SYS_ADMIN" for role in user.roles)
    next_is_admin = (
        any(role.role_code == "SYS_ADMIN" for role in next_roles)
        if next_roles is not None
        else current_is_admin
    )
    if user.status != 1 or not current_is_admin or (next_status == 1 and next_is_admin):
        return

    # Serialize operations that could remove the final active administrator.
    await lock_authz_version(session)
    active_admin_ids = list(
        (
            await session.scalars(
                select(User.id)
                .join(user_roles, user_roles.c.user_id == User.id)
                .join(Role, Role.id == user_roles.c.role_id)
                .where(User.status == 1, Role.role_code == "SYS_ADMIN")
                .with_for_update()
            )
        ).all()
    )
    if len(active_admin_ids) <= 1:
        raise ApiError("LAST_SYSTEM_ADMIN", "不能禁用或移除最后一个系统管理员", 409)


async def _load_user_for_response(session: AsyncSession, user_id: int) -> User:
    user = await session.scalar(
        select(User).options(selectinload(User.roles)).where(User.id == user_id)
    )
    if user is None:
        raise ApiError("USER_NOT_FOUND", "用户不存在", 404)
    return user


@router.get("/users", response_model=ApiResponse[dict[str, object]])
async def list_users(
    username: str | None = Query(default=None, max_length=64),
    real_name: str | None = Query(default=None, max_length=50),
    status: int | None = Query(default=None, ge=0, le=1),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, object]]:
    _require_admin(principal)
    page_offset(page, size)
    conditions = []
    if username:
        conditions.append(User.username.like(f"%{username.strip()}%"))
    if real_name:
        conditions.append(User.real_name.like(f"%{real_name.strip()}%"))
    if status is not None:
        conditions.append(User.status == status)
    total = int(await session.scalar(select(func.count(User.id)).where(*conditions)) or 0)
    page_ids = delayed_page_ids(
        select(User.id).where(*conditions),
        User.id,
        page=page,
        page_size=size,
    )
    rows = list(
        (
            await session.scalars(
                select(User)
                .join(page_ids, page_ids.c.id == User.id)
                .options(selectinload(User.roles))
                .order_by(User.id.desc())
            )
        ).all()
    )
    pages, truncated = page_metadata(total, size)
    return ApiResponse.ok(
        {
            "records": [_data(user) for user in rows],
            "total": total,
            "size": size,
            "current": page,
            "pages": pages,
            "truncated": truncated,
        }
    )


@router.post("/users", response_model=ApiResponse[dict[str, object]], status_code=201)
async def create_user(
    payload: UserRequest,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, object]]:
    _require_admin(principal)
    if not payload.password:
        raise ApiError("PASSWORD_REQUIRED", "创建用户时必须设置密码", 422)
    if await session.scalar(select(User).where(User.username == payload.username)) is not None:
        raise ApiError("USERNAME_TAKEN", "用户名已存在", 409)
    roles = await _roles(session, payload.role_codes)
    username = payload.username.strip()
    user = User(
        username=username,
        password_hash=hash_password(payload.password),
        real_name=payload.real_name,
        phone=payload.phone,
        email=payload.email,
        user_type=payload.user_type,
        college_id=await _resolve_college(
            session,
            payload.college_id,
            principal,
            allow_global="SYS_ADMIN" in payload.role_codes,
        ),
        status=1,
        roles=roles,
    )
    session.add(user)
    await session.flush()
    append_audit(
        session,
        user_id=principal.user_id,
        college_id=user.college_id,
        action="USER_CREATE",
        target_type="USER",
        target_id=user.id,
        detail={"username": user.username, "roles": payload.role_codes},
    )
    await session.commit()
    loaded = await session.scalar(
        select(User).options(selectinload(User.roles)).where(User.username == username)
    )
    if loaded is None:
        raise ApiError("USER_NOT_FOUND", "用户不存在", 404)
    return ApiResponse.ok(_data(loaded))


@router.put("/users/{user_id}", response_model=ApiResponse[dict[str, object]])
async def update_user(
    user_id: int,
    payload: UserRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, object]]:
    _require_admin(principal)
    user = await session.scalar(
        select(User).options(selectinload(User.roles)).where(User.id == user_id)
    )
    if user is None:
        raise ApiError("USER_NOT_FOUND", "用户不存在", 404)
    roles = await _roles(session, payload.role_codes)
    await _protect_last_system_admin(session, user, user.status, roles)
    roles_changed = {role.id for role in user.roles} != {role.id for role in roles}
    if payload.password:
        user.password_hash = hash_password(payload.password)
    user.real_name = payload.real_name
    user.phone = payload.phone
    user.email = payload.email
    user.user_type = payload.user_type
    user.college_id = await _resolve_college(
        session,
        payload.college_id,
        principal,
        allow_global="SYS_ADMIN" in payload.role_codes,
    )
    user.roles = roles
    if payload.password:
        try:
            await revoke_user_sessions(request, user.id)
        except SessionStoreUnavailable as exc:
            await session.rollback()
            raise ApiError(
                "AUTH_SESSION_UNAVAILABLE", "暂时无法安全更新密码，请稍后重试", 503
            ) from exc
    if roles_changed:
        await bump_authz_version(session)
    append_audit(
        session,
        user_id=principal.user_id,
        college_id=user.college_id,
        action="USER_UPDATE",
        target_type="USER",
        target_id=user.id,
        detail={"roles": payload.role_codes},
    )
    await session.commit()
    loaded = await _load_user_for_response(session, user_id)
    return ApiResponse.ok(_data(loaded))


@router.delete("/users/{user_id}", response_model=ApiResponse[None])
async def delete_user(
    user_id: int,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    _require_admin(principal)
    if user_id == principal.user_id:
        raise ApiError("SELF_DELETE_FORBIDDEN", "不能删除当前登录账号", 409)
    user = await session.scalar(
        select(User).options(selectinload(User.roles)).where(User.id == user_id)
    )
    if user is None:
        raise ApiError("USER_NOT_FOUND", "用户不存在", 404)
    await _protect_last_system_admin(session, user, 0)
    try:
        await revoke_user_sessions(request, user.id)
    except SessionStoreUnavailable:
        # The database status check blocks access even if Redis is unavailable.
        pass
    user.status = 0
    append_audit(
        session,
        user_id=principal.user_id,
        college_id=user.college_id,
        action="USER_DISABLE",
        target_type="USER",
        target_id=user.id,
    )
    await session.commit()
    return ApiResponse.ok(None)


@router.patch("/users/{user_id}/status", response_model=ApiResponse[None])
async def update_user_status(
    user_id: int,
    request: Request,
    status: int = Query(ge=0, le=1),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    _require_admin(principal)
    if user_id == principal.user_id and status == 0:
        raise ApiError("SELF_DISABLE_FORBIDDEN", "不能禁用当前登录账号", 409)
    user = await session.scalar(
        select(User).options(selectinload(User.roles)).where(User.id == user_id)
    )
    if user is None:
        raise ApiError("USER_NOT_FOUND", "用户不存在", 404)
    if (
        status == 1
        and user.college_id is None
        and not any(role.role_code == "SYS_ADMIN" for role in user.roles)
    ):
        raise ApiError("COLLEGE_REQUIRED", "启用普通用户前必须先分配所属学院", 422)
    await _protect_last_system_admin(session, user, status)
    if status == 0:
        try:
            await revoke_user_sessions(request, user.id)
        except SessionStoreUnavailable:
            # The active-user lookup reads MySQL on each request and fails closed.
            pass
    user.status = status
    append_audit(
        session,
        user_id=principal.user_id,
        college_id=user.college_id,
        action="USER_ENABLE" if status else "USER_DISABLE",
        target_type="USER",
        target_id=user.id,
    )
    await session.commit()
    return ApiResponse.ok(None)
