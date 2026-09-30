from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

import jwt
from fastapi import Depends, Request, WebSocket
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import get_authorization_snapshot
from app.auth.sessions import SessionStoreUnavailable, get_session
from app.core.errors import ApiError
from app.infrastructure.db.models import User
from app.infrastructure.db.session import get_db

password_hash = PasswordHash.recommended()


@dataclass(frozen=True)
class TokenClaims:
    session_id: str
    token_type: Literal["access"]
    token_id: str


@dataclass(frozen=True)
class Principal:
    user_id: int
    username: str
    college_id: int | None
    roles: tuple[str, ...]
    token_type: Literal["access"]
    token_id: str
    permissions: tuple[str, ...] = ()
    session_id: str = ""

    @property
    def is_system_admin(self) -> bool:
        return "SYS_ADMIN" in self.roles

    @property
    def is_lab_admin(self) -> bool:
        return "LAB_ADMIN" in self.roles or self.is_system_admin

    def has_permission(self, permission_code: str) -> bool:
        return self.is_system_admin or permission_code in self.permissions


def hash_password(value: str) -> str:
    return password_hash.hash(value)


def verify_password(value: str, hashed: str) -> bool:
    try:
        return password_hash.verify(value, hashed)
    except (ValueError, TypeError, UnknownHashError):
        # Existing Spring installations may still contain BCrypt hashes.
        # Unsupported legacy hashes are treated as invalid credentials.
        return False


def create_access_token(request: Request | WebSocket, *, session_id: str) -> str:
    settings = request.app.state.settings
    now = datetime.now(UTC)
    payload = {
        "sid": session_id,
        "type": "access",
        "jti": uuid4().hex,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_session_id(
    request: Request | WebSocket,
    token: str,
    *,
    allow_expired: bool = False,
) -> str:
    return str(_decode_access_payload(request, token, allow_expired=allow_expired)["sid"])


def _decode_access_payload(
    request: Request | WebSocket,
    token: str,
    *,
    allow_expired: bool,
) -> dict[str, object]:
    settings = request.app.state.settings
    options = {"require": ["sid", "type", "jti", "iss", "aud", "iat", "exp"]}
    if allow_expired:
        options["verify_exp"] = False
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options=options,
        )
    except jwt.PyJWTError as exc:
        raise ApiError("TOKEN_INVALID", "令牌无效或已过期", 401) from exc
    if payload.get("type") != "access":
        raise ApiError("TOKEN_TYPE_INVALID", "令牌类型不正确", 401)
    session_id = payload.get("sid")
    if not isinstance(session_id, str) or len(session_id) < 32:
        raise ApiError("TOKEN_INVALID", "令牌会话无效", 401)
    return payload


async def resolve_principal(
    request: Request | WebSocket,
    token: str,
    session: AsyncSession,
) -> Principal:
    payload = _decode_access_payload(request, token, allow_expired=False)
    session_id = str(payload["sid"])
    try:
        redis_session = await get_session(request, session_id)
    except SessionStoreUnavailable as exc:
        raise ApiError("AUTH_SESSION_UNAVAILABLE", "登录服务暂时不可用，请稍后重试", 503) from exc
    if redis_session is None:
        raise ApiError("AUTH_SESSION_INVALID", "登录已失效，请重新登录", 401)
    try:
        user_id = int(redis_session["user_id"])
        session_expires_at = int(redis_session["expires_at"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ApiError("AUTH_SESSION_INVALID", "登录会话无效，请重新登录", 401) from exc

    # Account enablement and the active tenant are deliberately read from the
    # relational source on every request, never trusted from a stale cache.
    user = await session.scalar(select(User).where(User.id == user_id, User.status == 1))
    if user is None:
        raise ApiError("USER_NOT_FOUND", "用户不存在或已禁用", 401)

    snapshot = await get_authorization_snapshot(
        request,
        session,
        user_id=user.id,
        session_id=session_id,
        session_expires_at=session_expires_at,
    )
    return Principal(
        user_id=user.id,
        username=user.username,
        college_id=user.college_id,
        roles=snapshot.roles,
        permissions=snapshot.permissions,
        token_type="access",
        token_id=str(payload["jti"]),
        session_id=session_id,
    )


async def get_current_principal(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> Principal:
    token = request.cookies.get(request.app.state.settings.access_cookie_name)
    if not token:
        raise ApiError("AUTH_REQUIRED", "请先登录", 401)
    return await resolve_principal(request, token, session)


async def get_current_user(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> User:
    user = await session.scalar(select(User).where(User.id == principal.user_id, User.status == 1))
    if user is None:
        raise ApiError("USER_NOT_FOUND", "用户不存在或已禁用", 401)
    return user


def require_permissions(*permission_codes: str):
    async def dependency(principal: Principal = Depends(get_current_principal)) -> Principal:
        missing = [code for code in permission_codes if not principal.has_permission(code)]
        if missing:
            raise ApiError("FORBIDDEN", "当前账号没有执行此操作的权限", 403)
        return principal

    return dependency


def require_roles(*required_roles: str):
    """Compatibility helper for domain identity checks; prefer permission codes."""

    async def dependency(principal: Principal = Depends(get_current_principal)) -> Principal:
        if not principal.is_system_admin and not set(required_roles).intersection(principal.roles):
            raise ApiError("FORBIDDEN", "当前角色无权执行此操作", 403)
        return principal

    return dependency


def college_scope(principal: Principal) -> int | None:
    if principal.is_system_admin:
        return None
    if principal.college_id is None:
        raise ApiError("COLLEGE_SCOPE_MISSING", "用户尚未绑定学院，无法访问业务数据", 403)
    return principal.college_id
