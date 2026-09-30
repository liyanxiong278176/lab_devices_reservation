from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import app.auth.sessions as sessions
import pytest
from app.auth.sessions import SessionStoreUnavailable
from app.core.settings import Settings
from redis.exceptions import WatchError


class MemoryPipeline:
    def __init__(self, redis: MemoryRedis) -> None:
        self.redis = redis
        self.commands: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    async def __aenter__(self) -> MemoryPipeline:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def watch(self, *_keys: str) -> None:
        if self.redis.watch_errors_remaining:
            self.redis.watch_errors_remaining -= 1
            raise WatchError
        return None

    async def exists(self, key: str) -> int:
        return int(self.redis.exists(key))

    async def hgetall(self, key: str) -> dict[str, str]:
        return await self.redis.hgetall(key)

    def multi(self) -> None:
        return None

    def hset(self, key: str, *, mapping: dict[str, str]) -> None:
        self.commands.append(("hset", (key,), {"mapping": mapping}))

    def expireat(self, key: str, expiry: int) -> None:
        self.commands.append(("expireat", (key, expiry), {}))

    def sadd(self, key: str, value: str) -> None:
        self.commands.append(("sadd", (key, value), {}))

    def delete(self, key: str) -> None:
        self.commands.append(("delete", (key,), {}))

    def srem(self, key: str, value: str) -> None:
        self.commands.append(("srem", (key, value), {}))

    def scard(self, key: str) -> None:
        self.commands.append(("scard", (key,), {}))

    async def execute(self) -> list[int]:
        results: list[int] = []
        for command, args, kwargs in self.commands:
            key = str(args[0])
            if command == "hset":
                self.redis.hashes.setdefault(key, {}).update(kwargs["mapping"])
                results.append(1)
            elif command == "expireat":
                results.append(1)
            elif command == "sadd":
                target = self.redis.sets.setdefault(key, set())
                previous = len(target)
                target.add(str(args[1]))
                results.append(int(len(target) > previous))
            elif command == "delete":
                removed = int(self.redis.hashes.pop(key, None) is not None)
                removed += int(self.redis.sets.pop(key, None) is not None)
                results.append(removed)
            elif command == "srem":
                target = self.redis.sets.get(key, set())
                previous = len(target)
                target.discard(str(args[1]))
                results.append(previous - len(target))
            elif command == "scard":
                results.append(len(self.redis.sets.get(key, set())))
        return results


class MemoryRedis:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.sets: dict[str, set[str]] = {}
        self.watch_errors_remaining = 0

    def pipeline(self, *, transaction: bool) -> MemoryPipeline:
        assert transaction is True
        return MemoryPipeline(self)

    def exists(self, key: str) -> bool:
        return key in self.hashes or key in self.sets

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

    async def hget(self, key: str, field: str) -> str | None:
        return self.hashes.get(key, {}).get(field)

    async def smembers(self, key: str) -> set[str]:
        return set(self.sets.get(key, set()))

    async def delete(self, key: str) -> int:
        removed = int(self.hashes.pop(key, None) is not None)
        removed += int(self.sets.pop(key, None) is not None)
        return removed

    async def aclose(self) -> None:
        return None


def request_for(redis: MemoryRedis) -> SimpleNamespace:
    app = SimpleNamespace(
        state=SimpleNamespace(
            settings=Settings(environment="test", _env_file=None),
            redis_client=redis,
        )
    )
    return SimpleNamespace(app=app)


@pytest.mark.asyncio
async def test_create_get_rotate_and_revoke_session_lifecycle() -> None:
    redis = MemoryRedis()
    request = request_for(redis)
    session_id = "s" * 43
    old_token = f"{session_id}.{'a' * 43}"
    new_token = f"{session_id}.{'b' * 43}"
    expiry = datetime.now(UTC) + timedelta(hours=1)

    assert await sessions.create_session(
        request,
        user_id=12,
        session_id=session_id,
        refresh_token=old_token,
        expires_at=expiry,
    )
    assert not await sessions.create_session(
        request,
        user_id=12,
        session_id=session_id,
        refresh_token=old_token,
        expires_at=expiry,
    )
    assert sessions.refresh_token_session_id(old_token) == session_id
    assert sessions.refresh_token_session_id("malformed") is None
    assert sessions.refresh_token_session_id(f"bad.{ 'x' * 43}") is None
    assert await sessions.get_session(request, session_id) == redis.hashes[
        sessions.session_key(session_id)
    ]

    outcome, user_id = await sessions.rotate_refresh_token(
        request,
        session_id=session_id,
        old_token=old_token,
        new_token=new_token,
    )
    assert (outcome, user_id) == ("rotated", 12)
    outcome, user_id = await sessions.rotate_refresh_token(
        request,
        session_id=session_id,
        old_token=old_token,
        new_token=f"{session_id}.{'c' * 43}",
    )
    assert (outcome, user_id) == ("reused", 12)
    assert await sessions.get_session(request, session_id) is None

    assert await sessions.revoke_user_sessions(request, 12) == 0
    assert await sessions.rotate_refresh_token(
        request,
        session_id=session_id,
        old_token=new_token,
        new_token=old_token,
    ) == ("missing", None)


@pytest.mark.asyncio
async def test_get_session_removes_corrupt_expired_and_nonpositive_user_records() -> None:
    redis = MemoryRedis()
    request = request_for(redis)

    corrupt_id = "c" * 43
    redis.hashes[sessions.session_key(corrupt_id)] = {"user_id": "4"}
    redis.sets[sessions.user_sessions_key(4)] = {corrupt_id}
    assert await sessions.get_session(request, corrupt_id) is None
    assert not redis.exists(sessions.session_key(corrupt_id))

    expired_id = "e" * 43
    redis.hashes[sessions.session_key(expired_id)] = {
        "user_id": "5",
        "expires_at": "1",
    }
    redis.sets[sessions.user_sessions_key(5)] = {expired_id}
    assert await sessions.get_session(request, expired_id) is None
    assert not redis.exists(sessions.session_key(expired_id))

    invalid_user_id = "u" * 43
    redis.hashes[sessions.session_key(invalid_user_id)] = {
        "user_id": "0",
        "expires_at": str(int((datetime.now(UTC) + timedelta(hours=1)).timestamp())),
    }
    assert await sessions.get_session(request, invalid_user_id) is None
    assert not redis.exists(sessions.session_key(invalid_user_id))


@pytest.mark.asyncio
async def test_refresh_rotation_expires_malformed_and_invalid_owner_records() -> None:
    redis = MemoryRedis()
    request = request_for(redis)
    expired_id = "x" * 43
    redis.hashes[sessions.session_key(expired_id)] = {
        "user_id": "31",
        "expires_at": "1",
        "refresh_hash": sessions.hash_refresh_token("old"),
    }
    redis.sets[sessions.user_sessions_key(31)] = {expired_id}
    assert await sessions.rotate_refresh_token(
        request,
        session_id=expired_id,
        old_token="old",
        new_token="new",
    ) == ("expired", 31)
    assert not redis.exists(sessions.session_key(expired_id))

    malformed_id = "m" * 43
    redis.hashes[sessions.session_key(malformed_id)] = {"user_id": "bad", "expires_at": "bad"}
    assert await sessions.rotate_refresh_token(
        request,
        session_id=malformed_id,
        old_token="old",
        new_token="new",
    ) == ("expired", None)

    invalid_owner_id = "z" * 43
    redis.hashes[sessions.session_key(invalid_owner_id)] = {
        "user_id": "0",
        "expires_at": str(int((datetime.now(UTC) + timedelta(hours=1)).timestamp())),
        "refresh_hash": sessions.hash_refresh_token("old"),
    }
    assert await sessions.rotate_refresh_token(
        request,
        session_id=invalid_owner_id,
        old_token="old",
        new_token="new",
    ) == ("reused", None)


@pytest.mark.asyncio
async def test_session_transactions_retry_watch_conflicts_and_stop_after_bounds() -> None:
    redis = MemoryRedis()
    request = request_for(redis)
    session_id = "w" * 43
    token = f"{session_id}.{'a' * 43}"
    expiry = datetime.now(UTC) + timedelta(hours=1)

    redis.watch_errors_remaining = 1
    assert await sessions.create_session(
        request,
        user_id=44,
        session_id=session_id,
        refresh_token=token,
        expires_at=expiry,
    )

    redis.watch_errors_remaining = 3
    assert not await sessions.create_session(
        request,
        user_id=44,
        session_id="q" * 43,
        refresh_token=token,
        expires_at=expiry,
    )

    redis.watch_errors_remaining = 4
    assert await sessions.rotate_refresh_token(
        request,
        session_id=session_id,
        old_token=token,
        new_token=f"{session_id}.{'b' * 43}",
    ) == ("reused", None)


@pytest.mark.asyncio
async def test_delete_and_revoke_sessions_clean_user_index_and_support_bad_user_values() -> None:
    redis = MemoryRedis()
    request = request_for(redis)
    first, second = "f" * 43, "g" * 43
    redis.hashes[sessions.session_key(first)] = {"user_id": "21"}
    redis.hashes[sessions.session_key(second)] = {"user_id": "not-an-integer"}
    redis.sets[sessions.user_sessions_key(21)] = {first}

    await sessions.delete_session(request, first, user_id=None)
    assert not redis.exists(sessions.session_key(first))
    assert not redis.exists(sessions.user_sessions_key(21))

    await sessions.delete_session(request, second, user_id=None)
    assert not redis.exists(sessions.session_key(second))

    ids = {"h" * 43, "i" * 43}
    redis.sets[sessions.user_sessions_key(22)] = ids
    for session_id in ids:
        redis.hashes[sessions.session_key(session_id)] = {"user_id": "22"}
    assert await sessions.revoke_user_sessions(request, 22) == 2
    assert not redis.exists(sessions.user_sessions_key(22))
    assert all(not redis.exists(sessions.session_key(item)) for item in ids)


@pytest.mark.asyncio
async def test_session_store_fails_closed_when_redis_is_unavailable() -> None:
    class BrokenRedis(MemoryRedis):
        async def hgetall(self, key: str) -> dict[str, str]:
            raise ConnectionError("redis unavailable")

    with pytest.raises(SessionStoreUnavailable):
        await sessions.get_session(request_for(BrokenRedis()), "s" * 43)


def test_session_expiry_helpers_use_utc_and_a_seven_day_lifetime() -> None:
    expiry_timestamp = int((datetime.now(UTC) + timedelta(hours=1)).timestamp())
    assert sessions.session_expiry_from_data({"expires_at": str(expiry_timestamp)}).tzinfo is UTC
    now = datetime(2026, 9, 28, tzinfo=UTC)
    assert sessions.session_expiry_from_now(now) == now + timedelta(days=7)
