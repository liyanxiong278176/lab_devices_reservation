from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.security import (
    create_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.common.response import ApiResponse
from app.core.errors import ApiError
from app.infrastructure.cache.rate_limit import enforce_login_rate_limit
from app.infrastructure.db.models import College, Role, User
from app.infrastructure.db.session import get_db

router = APIRouter()


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=6, max_length=128)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    real_name: str = Field(min_length=1, max_length=50)
    college_id: int


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=20)


class TokenData(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    real_name: str | None
    college_id: int | None
    roles: list[str]


async def _load_user(session: AsyncSession, username: str) -> User | None:
    return await session.scalar(
        select(User).options(selectinload(User.roles)).where(User.username == username)
    )


def _token_data(request: Request, user: User) -> TokenData:
    settings = request.app.state.settings
    return TokenData(
        access_token=create_token(request, user=user, token_type="access"),
        refresh_token=create_token(request, user=user, token_type="refresh"),
        expires_in=settings.access_token_minutes * 60,
    )


@router.post("/login", response_model=ApiResponse[TokenData])
async def login(
    request: Request,
    payload: LoginRequest,
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[TokenData]:
    await enforce_login_rate_limit(request, payload.username)
    user = await _load_user(session, payload.username)
    if (
        user is None
        or user.status != 1
        or not verify_password(payload.password, user.password_hash)
    ):
        raise ApiError("INVALID_CREDENTIALS", "用户名或密码错误", 401)
    return ApiResponse.ok(_token_data(request, user))


@router.post("/register", response_model=ApiResponse[UserData], status_code=201)
async def register(
    payload: RegisterRequest,
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[UserData]:
    existing = await session.scalar(select(User).where(User.username == payload.username))
    if existing is not None:
        raise ApiError("USERNAME_TAKEN", "用户名已存在", 409)
    college = await session.scalar(
        select(College).where(College.id == payload.college_id, College.status == 1)
    )
    if college is None:
        raise ApiError("COLLEGE_NOT_FOUND", "学院不存在或未启用", 400)
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        real_name=payload.real_name,
        user_type="STUDENT",
        college_id=college.id,
        status=1,
    )
    student_role = await session.scalar(select(Role).where(Role.role_code == "STUDENT"))
    if student_role is not None:
        user.roles.append(student_role)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return ApiResponse.ok(
        UserData(
            id=user.id,
            username=user.username,
            real_name=user.real_name,
            college_id=user.college_id,
            roles=[role.role_code for role in user.roles],
        )
    )


@router.post("/refresh", response_model=ApiResponse[TokenData])
async def refresh(
    request: Request,
    payload: RefreshRequest,
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[TokenData]:
    from app.auth.security import decode_token

    principal = decode_token(request, payload.refresh_token, expected_type="refresh")
    user = await session.scalar(
        select(User).options(selectinload(User.roles)).where(User.id == principal.user_id)
    )
    if user is None or user.status != 1:
        raise ApiError("USER_NOT_FOUND", "用户不存在或已禁用", 401)
    return ApiResponse.ok(_token_data(request, user))


@router.get("/me", response_model=ApiResponse[UserData])
async def me(user: User = Depends(get_current_user)) -> ApiResponse[UserData]:
    return ApiResponse.ok(
        UserData(
            id=user.id,
            username=user.username,
            real_name=user.real_name,
            college_id=user.college_id,
            roles=[role.role_code for role in user.roles],
        )
    )
