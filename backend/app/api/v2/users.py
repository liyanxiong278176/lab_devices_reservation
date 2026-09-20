from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.security import Principal, get_current_principal, hash_password
from app.common.response import ApiResponse
from app.core.errors import ApiError
from app.infrastructure.cache.rate_limit import enforce_authenticated_rate_limit
from app.infrastructure.db.models import College, Role, User
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


def _require_admin(principal: Principal) -> None:
    if not principal.is_system_admin:
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
    rows = list((await session.scalars(select(Role).where(Role.role_code.in_(codes)))).all())
    missing = set(codes) - {row.role_code for row in rows}
    if missing:
        raise ApiError("ROLE_NOT_FOUND", f"角色不存在: {', '.join(sorted(missing))}", 422)
    return rows


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
    conditions = []
    if username:
        conditions.append(User.username.like(f"%{username.strip()}%"))
    if real_name:
        conditions.append(User.real_name.like(f"%{real_name.strip()}%"))
    if status is not None:
        conditions.append(User.status == status)
    total = int(await session.scalar(select(func.count(User.id)).where(*conditions)) or 0)
    rows = list(
        (
            await session.scalars(
                select(User)
                .options(selectinload(User.roles))
                .where(*conditions)
                .order_by(User.id.desc())
                .offset((page - 1) * size)
                .limit(size)
            )
        ).all()
    )
    return ApiResponse.ok(
        {
            "records": [_data(user) for user in rows],
            "total": total,
            "size": size,
            "current": page,
            "pages": (total + size - 1) // size,
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
    await session.commit()
    loaded = await _load_user_for_response(session, user_id)
    return ApiResponse.ok(_data(loaded))


@router.delete("/users/{user_id}", response_model=ApiResponse[None])
async def delete_user(
    user_id: int,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    _require_admin(principal)
    if user_id == principal.user_id:
        raise ApiError("SELF_DELETE_FORBIDDEN", "不能删除当前登录账号", 409)
    user = await session.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise ApiError("USER_NOT_FOUND", "用户不存在", 404)
    user.status = 0
    await session.commit()
    return ApiResponse.ok(None)


@router.patch("/users/{user_id}/status", response_model=ApiResponse[None])
async def update_user_status(
    user_id: int,
    status: int = Query(ge=0, le=1),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    _require_admin(principal)
    if user_id == principal.user_id and status == 0:
        raise ApiError("SELF_DISABLE_FORBIDDEN", "不能禁用当前登录账号", 409)
    user = await session.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise ApiError("USER_NOT_FOUND", "用户不存在", 404)
    user.status = status
    await session.commit()
    return ApiResponse.ok(None)
