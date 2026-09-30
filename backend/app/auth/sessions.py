from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Request, WebSocket
from redis.exceptions import WatchError

from app.infrastructure.cache.redis import (
    REDIS_ERRORS,
    RedisCircuitOpen,
    get_redis,
    get_redis_circuit,
    redis_call,
)

SESSION_KEY_PREFIX = "lab:v2:auth:session:"
USER_SESSIONS_KEY_PREFIX = "lab:v2:auth:user-sessions:"
SESSION_LIFETIME = timedelta(days=7)
_RANDOM_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{40,64}$")


class SessionStoreUnavailable(RuntimeError):
    """The authoritative login-session store cannot be reached."""


def new_session_id() -> str:
    return secrets.token_urlsafe(32)


def new_refresh_token(session_id: str) -> str:
    # The random sid prefix lets a replay identify which session to revoke;
    # the independent 256-bit secret remains the actual refresh credential.
    return f"{session_id}.{secrets.token_urlsafe(32)}"


def refresh_token_session_id(value: str | None) -> str | None:
    if not value or "." not in value:
        return None
    session_id, secret = value.split(".", 1)
    if not _RANDOM_TOKEN_PATTERN.fullmatch(session_id) or not _RANDOM_TOKEN_PATTERN.fullmatch(
        secret
    ):
        return None
    return session_id


def hash_refresh_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def session_key(session_id: str) -> str:
    return f"{SESSION_KEY_PREFIX}{session_id}"


def user_sessions_key(user_id: int) -> str:
    return f"{USER_SESSIONS_KEY_PREFIX}{user_id}"


async def _run(request: Request | WebSocket, operation):
    timeout = max(0.05, float(request.app.state.settings.redis_socket_timeout_seconds))
    try:
        return await redis_call(
            get_redis_circuit(request.app),
            lambda: asyncio.wait_for(operation(), timeout=timeout),
        )
    except (*REDIS_ERRORS, RedisCircuitOpen, TimeoutError) as exc:
        raise SessionStoreUnavailable("authentication session store unavailable") from exc


async def create_session(
    request: Request,
    *,
    user_id: int,
    session_id: str,
    refresh_token: str,
    expires_at: datetime,
) -> bool:
    client = get_redis(request)
    absolute_expiry = int(expires_at.replace(tzinfo=UTC).timestamp())
    key = session_key(session_id)
    user_key = user_sessions_key(user_id)
    for _ in range(3):
        try:
            async with client.pipeline(transaction=True) as pipe:
                await pipe.watch(key)
                if await pipe.exists(key):
                    return False
                pipe.multi()
                pipe.hset(
                    key,
                    mapping={
                        "user_id": str(user_id),
                        "refresh_hash": hash_refresh_token(refresh_token),
                        "created_at": datetime.now(UTC).isoformat(),
                        "expires_at": str(absolute_expiry),
                    },
                )
                pipe.expireat(key, absolute_expiry)
                pipe.sadd(user_key, session_id)
                pipe.expireat(user_key, absolute_expiry)
                await _run(request, pipe.execute)
            return True
        except WatchError:
            continue
    return False


async def get_session(request: Request | WebSocket, session_id: str) -> dict[str, str] | None:
    data = await _run(request, lambda: get_redis(request).hgetall(session_key(session_id)))
    if not data:
        return None
    try:
        expiry = int(data["expires_at"])
        user_id = int(data["user_id"])
    except (KeyError, TypeError, ValueError):
        await delete_session(request, session_id, user_id=None)
        return None
    if expiry <= int(datetime.now(UTC).timestamp()) or user_id <= 0:
        await delete_session(request, session_id, user_id=user_id if user_id > 0 else None)
        return None
    return data


async def rotate_refresh_token(
    request: Request,
    *,
    session_id: str,
    old_token: str,
    new_token: str,
) -> tuple[str, int | None]:
    client = get_redis(request)
    key = session_key(session_id)
    old_hash = hash_refresh_token(old_token)
    new_hash = hash_refresh_token(new_token)
    now = int(datetime.now(UTC).timestamp())

    for _ in range(4):
        try:
            async with client.pipeline(transaction=True) as pipe:
                await pipe.watch(key)
                current = await pipe.hgetall(key)
                if not current:
                    return "missing", None
                try:
                    user_id = int(current["user_id"])
                    expires_at = int(current["expires_at"])
                except (KeyError, TypeError, ValueError):
                    user_id = 0
                    expires_at = 0
                current_hash = current.get("refresh_hash", "")
                if expires_at <= now:
                    pipe.multi()
                    pipe.delete(key)
                    if user_id > 0:
                        pipe.srem(user_sessions_key(user_id), session_id)
                    await _run(request, pipe.execute)
                    return "expired", user_id or None
                if user_id <= 0 or not hmac.compare_digest(current_hash, old_hash):
                    # Reuse of a previous refresh token revokes the complete
                    # login session, including its still-valid access JWT.
                    pipe.multi()
                    pipe.delete(key)
                    if user_id > 0:
                        pipe.srem(user_sessions_key(user_id), session_id)
                    await _run(request, pipe.execute)
                    return "reused", user_id or None
                pipe.multi()
                pipe.hset(
                    key,
                    mapping={
                        "refresh_hash": new_hash,
                        "last_rotated_at": datetime.now(UTC).isoformat(),
                    },
                )
                await _run(request, pipe.execute)
                return "rotated", user_id
        except WatchError:
            # A concurrent refresh changed the hash. Re-read; the old token
            # will then be classified as reuse and the session revoked.
            continue
    return "reused", None


async def delete_session(
    request: Request | WebSocket,
    session_id: str,
    *,
    user_id: int | None,
) -> None:
    if user_id is None:
        current = await _run(
            request,
            lambda: get_redis(request).hget(session_key(session_id), "user_id"),
        )
        try:
            user_id = int(current) if current is not None else None
        except (TypeError, ValueError):
            user_id = None
    client = get_redis(request)
    async with client.pipeline(transaction=True) as pipe:
        pipe.delete(session_key(session_id))
        if user_id is not None:
            user_key = user_sessions_key(user_id)
            pipe.srem(user_key, session_id)
            pipe.scard(user_key)
        results = await _run(request, pipe.execute)
    if user_id is not None and results and int(results[-1]) == 0:
        await _run(request, lambda: client.delete(user_sessions_key(user_id)))


async def revoke_user_sessions(request: Request, user_id: int) -> int:
    client = get_redis(request)
    user_key = user_sessions_key(user_id)
    session_ids = await _run(request, lambda: client.smembers(user_key))
    if not session_ids:
        return 0
    async with client.pipeline(transaction=True) as pipe:
        for session_id in session_ids:
            pipe.delete(session_key(str(session_id)))
        pipe.delete(user_key)
        await _run(request, pipe.execute)
    return len(session_ids)


def session_expiry_from_data(data: dict[str, str]) -> datetime:
    return datetime.fromtimestamp(int(data["expires_at"]), UTC)


def session_expiry_from_now(now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)) + SESSION_LIFETIME
