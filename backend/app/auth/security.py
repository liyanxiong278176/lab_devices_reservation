from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import ApiError
from app.infrastructure.db.models import User
from app.infrastructure.db.session import get_db

password_hash = PasswordHash.recommended()
bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    user_id: int
    username: str
    college_id: int | None
    roles: tuple[str, ...]
    token_type: Literal["access", "refresh"]
    token_id: str

    @property
    def is_system_admin(self) -> bool:
        return "SYS_ADMIN" in self.roles

    @property
    def is_lab_admin(self) -> bool:
        return "LAB_ADMIN" in self.roles or self.is_system_admin


def hash_password(value: str) -> str:
    return password_hash.hash(value)


def verify_password(value: str, hashed: str) -> bool:
    try:
        return password_hash.verify(value, hashed)
    except (ValueError, TypeError, UnknownHashError):
        # Existing Spring installations may still contain BCrypt hashes.
        # Treat an unsupported legacy hash as invalid credentials instead of
        # leaking a 500 from the login endpoint.
        return False


def create_token(
    request: Request,
    *,
    user: User,
    token_type: Literal["access", "refresh"],
) -> str:
    settings = request.app.state.settings
    now = datetime.now(UTC)
    ttl = (
        timedelta(minutes=settings.access_token_minutes)
        if token_type == "access"
        else timedelta(days=settings.refresh_token_days)
    )
    role_codes = tuple(role.role_code for role in user.roles)
    payload: dict[str, Any] = {
        "sub": str(user.id),
        "username": user.username,
        "college_id": user.college_id,
        "roles": role_codes,
        "type": token_type,
        "jti": uuid4().hex,
        "iss": settings.jwt_issuer,
        "iat": now,
        "exp": now + ttl,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(request: Request, token: str, expected_type: str = "access") -> Principal:
    settings = request.app.state.settings
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            options={"require": ["sub", "type", "jti", "iss", "exp"]},
        )
    except jwt.PyJWTError as exc:
        raise ApiError("TOKEN_INVALID", "令牌无效或已过期", 401) from exc

    if payload.get("type") != expected_type:
        raise ApiError("TOKEN_TYPE_INVALID", "令牌类型不正确", 401)
    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError) as exc:
        raise ApiError("TOKEN_INVALID", "令牌主体无效", 401) from exc
    return Principal(
        user_id=user_id,
        username=str(payload.get("username", "")),
        college_id=payload.get("college_id"),
        roles=tuple(str(value) for value in payload.get("roles", [])),
        token_type=expected_type,  # type: ignore[arg-type]
        token_id=str(payload["jti"]),
    )


async def get_current_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise ApiError("AUTH_REQUIRED", "请先登录", 401)
    return decode_token(request, credentials.credentials)


async def get_current_user(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db),
) -> User:
    user = await session.scalar(
        select(User)
        .options(selectinload(User.roles))
        .where(User.id == principal.user_id, User.status == 1)
    )
    if user is None:
        raise ApiError("USER_NOT_FOUND", "用户不存在或已禁用", 401)
    return user


def require_roles(*required_roles: str):
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
