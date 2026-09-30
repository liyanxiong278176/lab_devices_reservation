from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.csrf import (
    CSRF_ANONYMOUS_SESSION,
    csrf_token_session_id,
    issue_csrf_token,
)
from app.auth.rbac import bump_authz_version
from app.auth.security import (
    Principal,
    create_access_token,
    get_current_principal,
    get_current_user,
    hash_password,
    password_hash,
    verify_password,
)
from app.auth.sessions import (
    SESSION_LIFETIME,
    SessionStoreUnavailable,
    create_session,
    delete_session,
    new_refresh_token,
    new_session_id,
    refresh_token_session_id,
    rotate_refresh_token,
    session_expiry_from_now,
)
from app.common.response import ApiResponse
from app.core.errors import ApiError
from app.core.settings import Settings
from app.infrastructure.cache.rate_limit import (
    enforce_login_rate_limit,
    enforce_registration_rate_limit,
)
from app.infrastructure.db.models import College, Role, User
from app.infrastructure.db.session import get_db

router = APIRouter()

# A precomputed password-hash work factor keeps the nonexistent-account path
# comparable to an existing account without storing a real credential.
_DUMMY_PASSWORD_HASH = password_hash.hash("labflow-invalid-user-password-never-valid")


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=6, max_length=128)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    real_name: str = Field(min_length=1, max_length=50)
    college_id: int = Field(gt=0)


class SessionData(BaseModel):
    authenticated: bool = True
    expires_in: int
    csrf_token: str


class CsrfData(BaseModel):
    csrf_token: str


class PublicCollegeData(BaseModel):
    id: int
    code: str
    name: str


class UserData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    real_name: str | None
    college_id: int | None
    roles: list[str]
    permissions: list[str]
    credit_score: int = 100
    booking_blocked_until: datetime | None = None
    status: int = 1


async def _load_user(session: AsyncSession, username: str) -> User | None:
    return await session.scalar(
        select(User).options(selectinload(User.roles)).where(User.username == username)
    )


def _set_cookie(
    response: Response,
    settings: Settings,
    *,
    name: str,
    value: str,
    max_age: int,
    path: str,
    httponly: bool = True,
) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max(1, max_age),
        path=path,
        domain=settings.cookie_domain,
        secure=settings.cookie_secure,
        httponly=httponly,
        samesite="lax",
    )


def _set_session_cookies(
    response: Response,
    settings: Settings,
    *,
    session_id: str,
    access_token: str,
    refresh_token: str,
    expires_at: datetime,
    existing_csrf_token: str | None = None,
) -> str:
    access_age = settings.access_token_minutes * 60
    absolute_age = max(1, int((expires_at - datetime.now(UTC)).total_seconds()))
    _set_cookie(
        response,
        settings,
        name=settings.access_cookie_name,
        value=access_token,
        max_age=min(access_age, absolute_age),
        path=settings.api_prefix,
    )
    _set_cookie(
        response,
        settings,
        name=settings.refresh_cookie_name,
        value=refresh_token,
        max_age=absolute_age,
        path=f"{settings.api_prefix}/auth",
    )
    csrf_token = (
        existing_csrf_token
        if csrf_token_session_id(settings, existing_csrf_token) == session_id
        else issue_csrf_token(settings, session_id)
    )
    _set_cookie(
        response,
        settings,
        name=settings.csrf_cookie_name,
        value=csrf_token,
        max_age=absolute_age,
        path=settings.api_prefix,
    )
    return csrf_token


def _clear_session_cookies(response: Response, settings: Settings) -> None:
    for name, path in (
        (settings.access_cookie_name, settings.api_prefix),
        (settings.refresh_cookie_name, f"{settings.api_prefix}/auth"),
        (settings.csrf_cookie_name, settings.api_prefix),
    ):
        response.delete_cookie(
            name,
            path=path,
            domain=settings.cookie_domain,
            secure=settings.cookie_secure,
            httponly=True,
            samesite="lax",
        )


async def _issue_session(
    request: Request,
    response: Response,
    user: User,
) -> SessionData:
    expires_at = session_expiry_from_now()
    for _ in range(3):
        session_id = new_session_id()
        refresh_token = new_refresh_token(session_id)
        try:
            created = await create_session(
                request,
                user_id=user.id,
                session_id=session_id,
                refresh_token=refresh_token,
                expires_at=expires_at,
            )
        except SessionStoreUnavailable as exc:
            raise ApiError(
                "AUTH_SESSION_UNAVAILABLE", "登录服务暂时不可用，请稍后重试", 503
            ) from exc
        if not created:
            continue
        access_token = create_access_token(request, session_id=session_id)
        csrf_token = _set_session_cookies(
            response,
            request.app.state.settings,
            session_id=session_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
        )
        return SessionData(
            expires_in=request.app.state.settings.access_token_minutes * 60,
            csrf_token=csrf_token,
        )
    raise ApiError("AUTH_SESSION_CREATE_FAILED", "无法创建登录会话，请重试", 503)


@router.get("/csrf", response_model=ApiResponse[CsrfData])
async def get_csrf_token(request: Request, response: Response) -> ApiResponse[CsrfData]:
    settings = request.app.state.settings
    from app.auth.csrf import _csrf_session_id

    session_id = _csrf_session_id(request) or CSRF_ANONYMOUS_SESSION
    existing_token = request.cookies.get(settings.csrf_cookie_name)
    token = (
        existing_token
        if csrf_token_session_id(settings, existing_token) == session_id
        else issue_csrf_token(settings, session_id)
    )
    _set_cookie(
        response,
        settings,
        name=settings.csrf_cookie_name,
        value=token,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        path=settings.api_prefix,
    )
    return ApiResponse.ok(CsrfData(csrf_token=token))


@router.get("/colleges", response_model=ApiResponse[list[PublicCollegeData]])
async def public_colleges(
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[list[PublicCollegeData]]:
    rows = list(
        (
            await session.scalars(
                select(College)
                .where(College.status == 1)
                .order_by(College.name, College.id)
            )
        ).all()
    )
    return ApiResponse.ok(
        [PublicCollegeData(id=row.id, code=row.code, name=row.name) for row in rows]
    )


@router.post("/login", response_model=ApiResponse[SessionData])
async def login(
    request: Request,
    response: Response,
    payload: LoginRequest,
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[SessionData]:
    await enforce_login_rate_limit(request, payload.username)
    user = await _load_user(session, payload.username.strip())
    candidate_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    password_valid = verify_password(payload.password, candidate_hash)
    if user is None or user.status != 1 or not password_valid:
        raise ApiError("INVALID_CREDENTIALS", "用户名或密码错误", 401)
    if user.college_id is None and not any(role.role_code == "SYS_ADMIN" for role in user.roles):
        raise ApiError("COLLEGE_REQUIRED", "账号尚未绑定学院，暂时无法登录", 403)
    return ApiResponse.ok(await _issue_session(request, response, user))


@router.post("/register", response_model=ApiResponse[SessionData], status_code=201)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[SessionData]:
    username = payload.username.strip()
    await enforce_registration_rate_limit(request, username)
    college = await session.scalar(
        select(College).where(College.id == payload.college_id, College.status == 1)
    )
    if college is None:
        raise ApiError("COLLEGE_NOT_FOUND", "请选择有效的学院", 422)
    student_role = await session.scalar(select(Role).where(Role.role_code == "STUDENT"))
    if student_role is None:
        raise ApiError("ROLE_CONFIGURATION_MISSING", "普通用户角色未配置，请联系管理员", 503)
    user = User(
        username=username,
        password_hash=hash_password(payload.password),
        real_name=payload.real_name.strip(),
        user_type="STUDENT",
        college_id=college.id,
        status=1,
        roles=[student_role],
    )
    session.add(user)
    try:
        await session.flush()
        await bump_authz_version(session)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError("USERNAME_TAKEN", "用户名已被使用", 409) from exc
    await session.refresh(user)
    return ApiResponse.ok(await _issue_session(request, response, user))


@router.post("/refresh", response_model=ApiResponse[SessionData])
async def refresh(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[SessionData]:
    cookie_name = request.app.state.settings.refresh_cookie_name
    token = request.cookies.get(cookie_name)
    session_id = refresh_token_session_id(token)
    if token is None or session_id is None:
        raise ApiError("REFRESH_INVALID", "刷新会话无效，请重新登录", 401)
    try:
        current = await resolve_refresh_session(request, session_id, session)
    except SessionStoreUnavailable as exc:
        raise ApiError("AUTH_SESSION_UNAVAILABLE", "登录服务暂时不可用，请稍后重试", 503) from exc
    if current is None:
        raise ApiError("REFRESH_INVALID", "登录已失效，请重新登录", 401)
    user, absolute_expiry = current
    if user.status != 1:
        await delete_session(request, session_id, user_id=user.id)
        raise ApiError("USER_NOT_FOUND", "用户不存在或已禁用", 401)
    if absolute_expiry <= datetime.now(UTC):
        await delete_session(request, session_id, user_id=user.id)
        raise ApiError("REFRESH_EXPIRED", "登录已过期，请重新登录", 401)

    next_refresh = new_refresh_token(session_id)
    try:
        result, stored_user_id = await rotate_refresh_token(
            request,
            session_id=session_id,
            old_token=token,
            new_token=next_refresh,
        )
    except SessionStoreUnavailable as exc:
        raise ApiError("AUTH_SESSION_UNAVAILABLE", "登录服务暂时不可用，请稍后重试", 503) from exc
    if result == "reused":
        await request.app.state.notification_hub.disconnect_session(session_id)
        raise ApiError("REFRESH_REUSED", "检测到刷新令牌重放，请重新登录", 401)
    if result != "rotated" or stored_user_id != user.id:
        raise ApiError("REFRESH_INVALID", "登录已失效，请重新登录", 401)

    access_token = create_access_token(request, session_id=session_id)
    csrf_token = _set_session_cookies(
        response,
        request.app.state.settings,
        session_id=session_id,
        access_token=access_token,
        refresh_token=next_refresh,
        expires_at=absolute_expiry,
        existing_csrf_token=request.cookies.get(
            request.app.state.settings.csrf_cookie_name
        ),
    )
    return ApiResponse.ok(
        SessionData(
            expires_in=request.app.state.settings.access_token_minutes * 60,
            csrf_token=csrf_token,
        )
    )


async def resolve_refresh_session(
    request: Request,
    session_id: str,
    session: AsyncSession,
) -> tuple[User, datetime] | None:
    from app.auth.sessions import get_session, session_expiry_from_data

    redis_session = await get_session(request, session_id)
    if redis_session is None:
        return None
    try:
        user_id = int(redis_session["user_id"])
        expires_at = session_expiry_from_data(redis_session)
    except (KeyError, TypeError, ValueError) as exc:
        raise ApiError("AUTH_SESSION_INVALID", "登录会话无效", 401) from exc
    user = await session.scalar(select(User).where(User.id == user_id))
    if user is None:
        return None
    return user, expires_at


@router.post("/logout", response_model=ApiResponse[None])
async def logout(
    request: Request,
    response: Response,
    principal: Principal = Depends(get_current_principal),
) -> ApiResponse[None]:
    try:
        await delete_session(request, principal.session_id, user_id=principal.user_id)
    except SessionStoreUnavailable as exc:
        # Do not report a successful logout if the server could not revoke the
        # session. The client still clears local UI state after this response.
        raise ApiError("AUTH_SESSION_UNAVAILABLE", "退出登录暂时失败，请重试", 503) from exc
    await request.app.state.notification_hub.disconnect_session(principal.session_id)
    _clear_session_cookies(response, request.app.state.settings)
    return ApiResponse.ok(None)


@router.get("/me", response_model=ApiResponse[UserData])
async def me(
    user: User = Depends(get_current_user),
    principal: Principal = Depends(get_current_principal),
) -> ApiResponse[UserData]:
    return ApiResponse.ok(
        UserData(
            id=user.id,
            username=user.username,
            real_name=user.real_name,
            college_id=user.college_id,
            roles=list(principal.roles),
            permissions=list(principal.permissions),
            credit_score=user.credit_score,
            booking_blocked_until=user.booking_blocked_until,
            status=user.status,
        )
    )
