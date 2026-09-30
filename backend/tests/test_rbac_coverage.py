from __future__ import annotations

import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import app.auth.rbac as rbac
import pytest
from app.core.settings import Settings
from app.infrastructure.db.models import AuthorizationVersion


def request_for() -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(settings=Settings(environment="test", _env_file=None))
        )
    )


class SnapshotRedis:
    def __init__(self, cached: str | None = None, *, get_error: Exception | None = None,
                 set_error: Exception | None = None) -> None:
        self.cached = cached
        self.get_error = get_error
        self.set_error = set_error
        self.saved: tuple[str, str, int] | None = None

    async def get(self, _key: str) -> str | None:
        if self.get_error:
            raise self.get_error
        return self.cached

    async def set(self, key: str, value: str, *, ex: int) -> bool:
        if self.set_error:
            raise self.set_error
        self.saved = (key, value, ex)
        return True


@pytest.mark.asyncio
async def test_authorization_version_reads_increments_and_locks(seeded) -> None:
    factory, *_ = seeded
    async with factory() as session:
        assert await rbac.current_authz_version(session) == 1
        assert await rbac.bump_authz_version(session) == 2
        await rbac.lock_authz_version(session)
        row = await session.get(AuthorizationVersion, 1)
        assert row is not None and row.version == 2


@pytest.mark.asyncio
async def test_authorization_version_operations_fail_if_bootstrap_row_is_missing() -> None:
    session = SimpleNamespace(scalar=AsyncMock(return_value=None))
    with pytest.raises(RuntimeError, match="version row is missing"):
        await rbac.current_authz_version(session)
    with pytest.raises(RuntimeError, match="version row is missing"):
        await rbac.bump_authz_version(session)
    with pytest.raises(RuntimeError, match="version row is missing"):
        await rbac.lock_authz_version(session)


@pytest.mark.asyncio
async def test_database_snapshot_sorts_and_deduplicates_role_and_permission_codes(seeded) -> None:
    factory, _, _, student, *_ = seeded
    async with factory() as session:
        snapshot = await rbac._load_snapshot_from_database(session, student.id, 11)
        assert snapshot.version == 11
        assert snapshot.roles == ("STUDENT",)
        assert "device:read" in snapshot.permissions
        assert tuple(sorted(set(snapshot.permissions))) == snapshot.permissions

        absent_user_snapshot = await rbac._load_snapshot_from_database(session, -1, 11)
        assert absent_user_snapshot.roles == ()
        assert absent_user_snapshot.permissions == ()


@pytest.mark.asyncio
async def test_authorization_snapshot_cache_hit_and_database_fill_use_bounded_ttl(
    monkeypatch: pytest.MonkeyPatch,
    seeded,
) -> None:
    factory, _, _, student, *_ = seeded
    request = request_for()
    monkeypatch.setattr(rbac.time, "time", lambda: 1_000)
    monkeypatch.setattr(
        rbac,
        "_redis_operation",
        lambda _request, operation: operation(),
    )
    cache = SnapshotRedis()
    monkeypatch.setattr(rbac, "get_redis", lambda _request: cache)

    async with factory() as session:
        loaded = await rbac.get_authorization_snapshot(
            request,
            session,
            user_id=student.id,
            session_id="sid-cache",
            session_expires_at=1_020,
        )
        assert loaded.roles == ("STUDENT",)
        assert cache.saved is not None
        key, encoded, ttl = cache.saved
        assert key == rbac.permission_cache_key("sid-cache", 1)
        assert ttl == 20
        assert json.loads(encoded)["roles"] == ["STUDENT"]

        cache.cached = json.dumps(
            {"version": 1, "roles": ["CACHED"], "permissions": ["cached:read"]}
        )
        cached = await rbac.get_authorization_snapshot(
            request,
            session,
            user_id=student.id,
            session_id="sid-cache",
            session_expires_at=10_000,
        )
        assert cached.roles == ("CACHED",)
        assert cached.permissions == ("cached:read",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cached",
    [
        "not-json",
        "[]",
        json.dumps({"version": 99, "roles": [], "permissions": []}),
        json.dumps({"version": 1, "roles": "bad", "permissions": []}),
    ],
)
async def test_invalid_permission_cache_payload_falls_back_to_database(
    monkeypatch: pytest.MonkeyPatch,
    seeded,
    cached: str,
) -> None:
    factory, _, _, student, *_ = seeded
    request = request_for()
    monkeypatch.setattr(rbac, "_redis_operation", lambda _request, operation: operation())
    cache = SnapshotRedis(cached)
    monkeypatch.setattr(rbac, "get_redis", lambda _request: cache)

    async with factory() as session:
        snapshot = await rbac.get_authorization_snapshot(
            request,
            session,
            user_id=student.id,
            session_id="sid-invalid",
            session_expires_at=int(time.time()) + 600,
        )
        assert snapshot.roles == ("STUDENT",)
        assert cache.saved is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [ConnectionError("redis down"), TimeoutError()])
async def test_redis_read_or_write_failure_preserves_database_authorization(
    monkeypatch: pytest.MonkeyPatch,
    seeded,
    failure: Exception,
) -> None:
    factory, _, _, student, *_ = seeded
    request = request_for()
    monkeypatch.setattr(rbac, "_redis_operation", lambda _request, operation: operation())
    cache = SnapshotRedis(get_error=failure)
    monkeypatch.setattr(rbac, "get_redis", lambda _request: cache)

    async with factory() as session:
        snapshot = await rbac.get_authorization_snapshot(
            request,
            session,
            user_id=student.id,
            session_id="sid-fallback",
            session_expires_at=int(time.time()) + 60,
        )
        assert snapshot.roles == ("STUDENT",)
        assert cache.saved is None

    cache = SnapshotRedis(set_error=failure)
    monkeypatch.setattr(rbac, "get_redis", lambda _request: cache)
    async with factory() as session:
        snapshot = await rbac.get_authorization_snapshot(
            request,
            session,
            user_id=student.id,
            session_id="sid-write-fail",
            session_expires_at=int(time.time()) + 60,
        )
        assert snapshot.roles == ("STUDENT",)
