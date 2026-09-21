from datetime import UTC, datetime, timedelta
from uuid import uuid4

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
from app.infrastructure.db.models import College, RefreshSession, Role, User
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
    credit_score: int = 100
    booking_blocked_until: datetime | None = None


async def _load_user(session: AsyncSession, username: str) -> User | None:
    return await session.scalar(
        select(User).options(selectinload(User.roles)).where(User.username == username)
    )


def _token_data(request: Request, user: User, refresh_token_id: str) -> TokenData:
    settings = request.app.state.settings
    return TokenData(
        access_token=create_token(request, user=user, token_type="access"),
        refresh_token=create_token(
            request,
            user=user,
            token_type="refresh",
            token_id=refresh_token_id,
        ),
        expires_in=settings.access_token_minutes * 60,
    )


async def _issue_tokens(
    request: Request,
    session: AsyncSession,
    user: User,
) -> TokenData:
    settings = request.app.state.settings
    refresh_token_id = uuid4().hex
    data = _token_data(request, user, refresh_token_id)
    session.add(
        RefreshSession(
            token_id=refresh_token_id,
            user_id=user.id,
            expires_at=datetime.now(UTC).replace(tzinfo=None)
            + timedelta(days=settings.refresh_token_days),
        )
    )
    await session.commit()
    return data


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
    return ApiResponse.ok(await _issue_tokens(request, session, user))


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
            credit_score=user.credit_score,
            booking_blocked_until=user.booking_blocked_until,
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
    now = datetime.now(UTC).replace(tzinfo=None)
    old_session = await session.scalar(
        select(RefreshSession)
        .where(
            RefreshSession.token_id == principal.token_id,
            RefreshSession.user_id == user.id,
            RefreshSession.revoked_at.is_(None),
            RefreshSession.expires_at > now,
        )
        .with_for_update()
    )
    if old_session is None:
        raise ApiError("REFRESH_REUSED", "刷新令牌已失效，请重新登录", 401)
    new_refresh_id = uuid4().hex
    old_session.revoked_at = now
    old_session.replaced_by = new_refresh_id
    data = _token_data(request, user, new_refresh_id)
    session.add(
        RefreshSession(
            token_id=new_refresh_id,
            user_id=user.id,
            expires_at=now + timedelta(days=request.app.state.settings.refresh_token_days),
        )
    )
    await session.commit()
    return ApiResponse.ok(data)


@router.post("/logout", response_model=ApiResponse[None])
async def logout(
    request: Request,
    payload: RefreshRequest,
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    from app.auth.security import decode_token

    principal = decode_token(request, payload.refresh_token, expected_type="refresh")
    await session.execute(
        RefreshSession.__table__.update()
        .where(
            RefreshSession.token_id == principal.token_id,
            RefreshSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC).replace(tzinfo=None))
    )
    await session.commit()
    return ApiResponse.ok(None)


@router.get("/me", response_model=ApiResponse[UserData])
async def me(user: User = Depends(get_current_user)) -> ApiResponse[UserData]:
    return ApiResponse.ok(
        UserData(
            id=user.id,
            username=user.username,
            real_name=user.real_name,
            college_id=user.college_id,
            roles=[role.role_code for role in user.roles],
            credit_score=user.credit_score,
            booking_blocked_until=user.booking_blocked_until,
        )
    )
