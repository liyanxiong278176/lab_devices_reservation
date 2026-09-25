import asyncio
from datetime import UTC, datetime, timedelta
from time import perf_counter
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
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
from app.infrastructure.cache.rate_limit import (
    enforce_login_rate_limit,
    enforce_registration_rate_limit,
)
from app.infrastructure.db.models import RefreshSession, Role, User
from app.infrastructure.db.session import get_db

router = APIRouter()
_REGISTRATION_RESPONSE_FLOOR_SECONDS = 0.5


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=6, max_length=128)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    real_name: str = Field(min_length=1, max_length=50)
    # Kept optional for old clients; the submitted value is only a claim and
    # is never written as the user's effective tenant assignment.
    college_id: int | None = Field(default=None, gt=0)


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
    status: int = 1


async def _load_user(session: AsyncSession, username: str) -> User | None:
    return await session.scalar(
        select(User).options(selectinload(User.roles)).where(User.username == username)
    )


def _token_data(
    request: Request,
    user: User,
    refresh_token_id: str,
    family_id: str,
) -> TokenData:
    settings = request.app.state.settings
    return TokenData(
        access_token=create_token(
            request,
            user=user,
            token_type="access",
            session_id=family_id,
        ),
        refresh_token=create_token(
            request,
            user=user,
            token_type="refresh",
            token_id=refresh_token_id,
            session_id=family_id,
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
    family_id = uuid4().hex
    data = _token_data(request, user, refresh_token_id, family_id)
    session.add(
        RefreshSession(
            token_id=refresh_token_id,
            family_id=family_id,
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


@router.post("/register", response_model=ApiResponse[dict[str, bool]], status_code=202)
async def register(
    payload: RegisterRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, bool]]:
    started_at = perf_counter()
    await enforce_registration_rate_limit(request, payload.username)
    candidate_password_hash = hash_password(payload.password)
    # Keep the public response identical for new and already-registered names.
    # The unique constraint remains the final arbiter for concurrent submits.
    async def accepted() -> ApiResponse[dict[str, bool]]:
        remaining = _REGISTRATION_RESPONSE_FLOOR_SECONDS - (perf_counter() - started_at)
        if remaining > 0:
            await asyncio.sleep(remaining)
        return ApiResponse(
            code="OK",
            message="请求已受理；如申请符合条件，将按流程处理",
            data={"received": True},
        )

    existing = await session.scalar(select(User.id).where(User.username == payload.username))
    if existing is not None:
        return await accepted()
    user = User(
        username=payload.username,
        password_hash=candidate_password_hash,
        real_name=payload.real_name,
        user_type="STUDENT",
        college_id=None,
        # A self-declared college is only a claim. The account remains unable
        # to authenticate until a system admin verifies and activates it.
        status=0,
    )
    student_role = await session.scalar(select(Role).where(Role.role_code == "STUDENT"))
    if student_role is not None:
        user.roles.append(student_role)
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await session.scalar(select(User.id).where(User.username == payload.username))
        if existing is None:
            raise
    return await accepted()


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
            RefreshSession.family_id == principal.session_id,
        )
        .with_for_update()
    )
    if old_session is None:
        raise ApiError("REFRESH_REUSED", "刷新令牌已失效，请重新登录", 401)
    if old_session.revoked_at is not None:
        if old_session.replaced_by is not None:
            # A rotated refresh token was presented again. Revoke every active
            # descendant before returning the error so the successor cannot
            # continue minting credentials.
            await session.execute(
                update(RefreshSession)
                .where(
                    RefreshSession.family_id == old_session.family_id,
                    RefreshSession.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
            await session.commit()
            await request.app.state.notification_hub.disconnect_session(old_session.family_id)
        raise ApiError("REFRESH_REUSED", "刷新令牌已失效，请重新登录", 401)
    if old_session.expires_at <= now:
        raise ApiError("REFRESH_REUSED", "刷新令牌已失效，请重新登录", 401)
    new_refresh_id = uuid4().hex
    old_session.revoked_at = now
    old_session.replaced_by = new_refresh_id
    data = _token_data(request, user, new_refresh_id, old_session.family_id)
    session.add(
        RefreshSession(
            token_id=new_refresh_id,
            family_id=old_session.family_id,
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
        update(RefreshSession)
        .where(
            RefreshSession.family_id == principal.session_id,
            RefreshSession.user_id == principal.user_id,
            RefreshSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC).replace(tzinfo=None))
    )
    await session.commit()
    await request.app.state.notification_hub.disconnect_session(principal.session_id)
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
            status=user.status,
        )
    )
