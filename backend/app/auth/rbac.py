from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass

from fastapi import Request, WebSocket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.infrastructure.cache.redis import (
    REDIS_ERRORS,
    RedisCircuitOpen,
    get_redis,
    get_redis_circuit,
    redis_call,
)
from app.infrastructure.db.models import AuthorizationVersion, Role, user_roles

AUTHZ_VERSION_ID = 1
PERMISSION_CACHE_TTL_SECONDS = 300


@dataclass(frozen=True)
class AuthorizationSnapshot:
    version: int
    roles: tuple[str, ...]
    permissions: tuple[str, ...]


async def current_authz_version(session: AsyncSession) -> int:
    version = await session.scalar(
        select(AuthorizationVersion.version).where(AuthorizationVersion.id == AUTHZ_VERSION_ID)
    )
    if version is None:
        raise RuntimeError("authorization version row is missing; apply migrations first")
    return int(version)


async def bump_authz_version(session: AsyncSession) -> int:
    row = await session.scalar(
        select(AuthorizationVersion)
        .where(AuthorizationVersion.id == AUTHZ_VERSION_ID)
        .with_for_update()
    )
    if row is None:
        raise RuntimeError("authorization version row is missing; apply migrations first")
    row.version += 1
    await session.flush()
    return int(row.version)


async def lock_authz_version(session: AsyncSession) -> None:
    row = await session.scalar(
        select(AuthorizationVersion)
        .where(AuthorizationVersion.id == AUTHZ_VERSION_ID)
        .with_for_update()
    )
    if row is None:
        raise RuntimeError("authorization version row is missing; apply migrations first")


def permission_cache_key(session_id: str, version: int) -> str:
    return f"lab:v2:auth:session:{session_id}:permissions:v{version}"


async def _redis_operation(request: Request | WebSocket, operation):
    timeout = max(0.05, float(request.app.state.settings.redis_socket_timeout_seconds))
    return await redis_call(
        get_redis_circuit(request.app),
        lambda: asyncio.wait_for(operation(), timeout=timeout),
    )


async def _load_snapshot_from_database(
    session: AsyncSession,
    user_id: int,
    version: int,
) -> AuthorizationSnapshot:
    roles = list(
        (
            await session.scalars(
                select(Role)
                .join(user_roles, user_roles.c.role_id == Role.id)
                .where(user_roles.c.user_id == user_id)
                .options(selectinload(Role.permissions))
            )
        ).all()
    )
    role_codes = tuple(sorted({role.role_code for role in roles}))
    permission_codes = tuple(
        sorted({permission.permission_code for role in roles for permission in role.permissions})
    )
    return AuthorizationSnapshot(version, role_codes, permission_codes)


async def get_authorization_snapshot(
    request: Request | WebSocket,
    session: AsyncSession,
    *,
    user_id: int,
    session_id: str,
    session_expires_at: int,
) -> AuthorizationSnapshot:
    version = await current_authz_version(session)
    key = permission_cache_key(session_id, version)
    client = get_redis(request)
    cache_available = True
    try:
        cached = await _redis_operation(request, lambda: client.get(key))
    except (*REDIS_ERRORS, RedisCircuitOpen, TimeoutError):
        # Session lookup is authoritative and already succeeded. A permission
        # cache miss/failure is safe to fall back to the relational source.
        cached = None
        cache_available = False
    if cached:
        try:
            payload = json.loads(cached)
            if (
                payload.get("version") == version
                and isinstance(payload.get("roles"), list)
                and isinstance(payload.get("permissions"), list)
            ):
                return AuthorizationSnapshot(
                    version,
                    tuple(str(code) for code in payload["roles"]),
                    tuple(str(code) for code in payload["permissions"]),
                )
        except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
            pass

    snapshot = await _load_snapshot_from_database(session, user_id, version)
    if cache_available:
        remaining = max(1, session_expires_at - int(time.time()))
        ttl = min(PERMISSION_CACHE_TTL_SECONDS, remaining)
        encoded = json.dumps(
            {
                "version": snapshot.version,
                "roles": snapshot.roles,
                "permissions": snapshot.permissions,
            },
            separators=(",", ":"),
        )
        try:
            # The key embeds the DB version. If a concurrent authorization
            # change commits, subsequent requests read the new version and
            # never consume this older snapshot.
            await _redis_operation(request, lambda: client.set(key, encoded, ex=ttl))
        except (*REDIS_ERRORS, RedisCircuitOpen, TimeoutError):
            pass
    return snapshot
