"""Opt-in checks against a real Redis instance and its fail-open path."""

from __future__ import annotations

import asyncio
import os
import secrets
from datetime import date, timedelta

import pytest
from app.api.v2.schemas import ReservationPlanRequest
from app.application.reservations import ReservationService
from app.auth.security import Principal
from app.core.errors import ApiError
from app.core.settings import Settings
from app.infrastructure.cache.redis import (
    _release_locks,
    dispose_app_redis,
    get_redis_for_app,
    reservation_lock,
)
from app.infrastructure.db.models import Device, ReservationItem, User
from app.infrastructure.db.session import build_engine, build_session_factory
from fastapi import FastAPI, Request
from scripts.e2e_fixture import cleanup, seed
from sqlalchemy import func, select


def _request(app: FastAPI) -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.0"},
            "http_version": "1.1",
            "server": ("127.0.0.1", 8000),
            "client": ("127.0.0.1", 12345),
            "scheme": "http",
            "method": "POST",
            "path": "/api/v2/reservations",
            "raw_path": b"/api/v2/reservations",
            "query_string": b"",
            "headers": [],
            "app": app,
            "state": {},
        }
    )


@pytest.mark.asyncio
async def test_real_redis_reservation_lock_acquires_releases_and_times_out() -> None:
    if os.getenv("LAB_RUN_REDIS_INTEGRATION") != "1":
        pytest.skip("set LAB_RUN_REDIS_INTEGRATION=1 to test the configured Redis")

    settings = Settings().model_copy(
        update={
            "reservation_lock_wait_seconds": 0.1,
            "reservation_lock_poll_seconds": 0.01,
        }
    )
    app = FastAPI()
    app.state.settings = settings
    request = _request(app)
    client = get_redis_for_app(app)
    device_id = secrets.randbelow(1_000_000_000) + 1_000_000_000
    reservation_date = date.today() + timedelta(days=365)
    key = f"lab:v2:reservation:{device_id}:{reservation_date.isoformat()}"

    try:
        await client.ping()
        async with reservation_lock(request, device_id, [reservation_date]) as acquired:
            assert acquired is True
            assert await client.get(key) is not None

            async def contend_from_another_task() -> bool:
                async with reservation_lock(request, device_id, [reservation_date]) as contended:
                    return contended

            assert await asyncio.create_task(contend_from_another_task()) is False
        assert await client.get(key) is None
    finally:
        await dispose_app_redis(app)


@pytest.mark.asyncio
async def test_real_redis_partially_overlapping_date_ranges_contend_without_leaking_locks() -> None:
    if os.getenv("LAB_RUN_REDIS_INTEGRATION") != "1":
        pytest.skip("set LAB_RUN_REDIS_INTEGRATION=1 to test the configured Redis")

    settings = Settings().model_copy(
        update={
            "reservation_lock_wait_seconds": 0.1,
            "reservation_lock_poll_seconds": 0.01,
        }
    )
    app = FastAPI()
    app.state.settings = settings
    request = _request(app)
    client = get_redis_for_app(app)
    device_id = secrets.randbelow(1_000_000_000) + 1_000_000_000
    first_date = date.today() + timedelta(days=365)
    first_range = [first_date + timedelta(days=1), first_date + timedelta(days=2)]
    overlapping_range = [first_date, first_date + timedelta(days=1)]
    first_only_key = f"lab:v2:reservation:{device_id}:{first_range[1].isoformat()}"
    shared_key = f"lab:v2:reservation:{device_id}:{first_range[0].isoformat()}"
    second_only_key = f"lab:v2:reservation:{device_id}:{first_date.isoformat()}"

    try:
        await client.ping()
        async with reservation_lock(request, device_id, first_range) as acquired:
            assert acquired is True

            async def contend_from_another_task() -> bool:
                async with reservation_lock(request, device_id, overlapping_range) as contended:
                    return contended

            assert await asyncio.create_task(contend_from_another_task()) is False
            # The second range acquired its earlier, non-overlapping date
            # before reaching the shared date; it must release that partial lock.
            assert await client.get(second_only_key) is None
            # Its failed acquisition must not release the first range's lock.
            assert await client.get(shared_key) is not None
            assert await client.get(first_only_key) is not None

        assert await client.get(shared_key) is None
        assert await client.get(first_only_key) is None
        assert await client.get(second_only_key) is None
    finally:
        await dispose_app_redis(app)


@pytest.mark.asyncio
async def test_real_redis_reservation_lock_is_reentrant_for_same_async_task() -> None:
    if os.getenv("LAB_RUN_REDIS_INTEGRATION") != "1":
        pytest.skip("set LAB_RUN_REDIS_INTEGRATION=1 to test the configured Redis")

    settings = Settings().model_copy(
        update={
            "reservation_lock_ttl_seconds": 2,
            "reservation_lock_wait_seconds": 0.1,
            "reservation_lock_poll_seconds": 0.01,
        }
    )
    app = FastAPI()
    app.state.settings = settings
    request = _request(app)
    client = get_redis_for_app(app)
    device_id = secrets.randbelow(1_000_000_000) + 1_000_000_000
    reservation_date = date.today() + timedelta(days=365)
    key = f"lab:v2:reservation:{device_id}:{reservation_date.isoformat()}"

    try:
        await client.ping()
        async with reservation_lock(request, device_id, [reservation_date]) as acquired:
            assert acquired is True
            async with reservation_lock(request, device_id, [reservation_date]) as reentrant:
                assert reentrant is True
                assert (await client.get(key)).endswith("|2")

            # Releasing the inner acquisition decrements the hold count instead
            # of deleting the outer task's lock.
            assert (await client.get(key)).endswith("|1")

            async def contend_from_another_task() -> bool:
                async with reservation_lock(request, device_id, [reservation_date]) as contended:
                    return contended

            assert await asyncio.create_task(contend_from_another_task()) is False

        assert await client.get(key) is None
    finally:
        await dispose_app_redis(app)


@pytest.mark.asyncio
async def test_real_redis_reservation_lock_watchdog_renews_long_lease() -> None:
    if os.getenv("LAB_RUN_REDIS_INTEGRATION") != "1":
        pytest.skip("set LAB_RUN_REDIS_INTEGRATION=1 to test the configured Redis")

    settings = Settings().model_copy(
        update={
            "reservation_lock_ttl_seconds": 1,
            "reservation_lock_wait_seconds": 0.08,
            "reservation_lock_poll_seconds": 0.01,
        }
    )
    app = FastAPI()
    app.state.settings = settings
    request = _request(app)
    client = get_redis_for_app(app)
    device_id = secrets.randbelow(1_000_000_000) + 1_000_000_000
    reservation_date = date.today() + timedelta(days=365)
    key = f"lab:v2:reservation:{device_id}:{reservation_date.isoformat()}"

    try:
        await client.ping()
        async with reservation_lock(request, device_id, [reservation_date]) as acquired:
            assert acquired is True
            await asyncio.sleep(1.3)
            assert await client.get(key) is not None
            assert await client.pttl(key) > 0

            async def contend_from_another_task() -> bool:
                async with reservation_lock(request, device_id, [reservation_date]) as contended:
                    return contended

            assert await asyncio.create_task(contend_from_another_task()) is False

        assert await client.get(key) is None
    finally:
        await dispose_app_redis(app)


@pytest.mark.asyncio
async def test_real_redis_stale_owner_cannot_release_reacquired_lock() -> None:
    if os.getenv("LAB_RUN_REDIS_INTEGRATION") != "1":
        pytest.skip("set LAB_RUN_REDIS_INTEGRATION=1 to test the configured Redis")

    app = FastAPI()
    app.state.settings = Settings()
    client = get_redis_for_app(app)
    device_id = secrets.randbelow(1_000_000_000) + 1_000_000_000
    key = f"lab:v2:reservation:{device_id}:{date.today().isoformat()}"
    stale_owner = f"client:{secrets.token_hex(12)}"
    current_owner = f"client:{secrets.token_hex(12)}"
    ttl_ms = 5000

    try:
        await client.ping()
        await client.set(key, f"{current_owner}|1", px=ttl_ms)

        await _release_locks(client, [key], stale_owner, ttl_ms)

        assert await client.get(key) == f"{current_owner}|1"
        await _release_locks(client, [key], current_owner, ttl_ms)
        assert await client.get(key) is None
    finally:
        await dispose_app_redis(app)


@pytest.mark.asyncio
async def test_mysql_unique_guard_wins_when_redis_is_unavailable() -> None:
    if os.getenv("LAB_RUN_MYSQL_INTEGRATION") != "1":
        pytest.skip("set LAB_RUN_MYSQL_INTEGRATION=1 to test against the configured MySQL")

    settings = Settings()
    if settings.mysql_dsn.startswith("sqlite"):
        pytest.skip("this test verifies MySQL unique-index semantics")

    prefix = f"e2e-redis-down-race-{secrets.token_hex(4)}"
    engine = None
    app: FastAPI | None = None
    try:
        await seed(prefix)
        engine = build_engine(settings)
        factory = build_session_factory(engine)
        async with factory() as session:
            student = await session.scalar(select(User).where(User.username == f"{prefix}-user"))
            device = await session.scalar(select(Device).where(Device.name == f"{prefix}-device"))
            assert student is not None and device is not None
            principal = Principal(
                user_id=student.id,
                username=student.username,
                college_id=student.college_id,
                roles=("STUDENT",),
                token_type="access",
                token_id=f"redis-down-race-{secrets.token_hex(6)}",
                permissions=("reservation:create",),
            )
            device_id = device.id

        app = FastAPI()
        app.state.settings = settings.model_copy(
            update={
                "redis_url": "redis://127.0.0.1:1/0",
                "redis_socket_timeout_seconds": 0.05,
                "reservation_lock_wait_seconds": 0.1,
                "redis_circuit_failure_threshold": 1,
            }
        )
        request = _request(app)
        target_date = date.today() + timedelta(days=10)

        async def submit(contender: int):
            async with reservation_lock(request, device_id, [target_date]) as acquired:
                assert acquired is False
                async with factory() as session:
                    return await ReservationService(session, principal).create(
                        ReservationPlanRequest(
                            device_id=device_id,
                            start_date=target_date,
                            end_date=target_date,
                            purpose=f"Redis 故障降级并发验证 {contender}",
                        ),
                        idempotency_key=f"{prefix}-request-{contender}",
                    )

        outcomes = await asyncio.gather(
            *(submit(contender) for contender in range(8)),
            return_exceptions=True,
        )
        successes = [outcome for outcome in outcomes if not isinstance(outcome, BaseException)]
        failures = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
        assert len(successes) == 1, outcomes
        assert len(failures) == 7, outcomes
        assert all(isinstance(error, ApiError) and error.status_code == 409 for error in failures)

        async with factory() as session:
            occupied_rows = int(
                await session.scalar(
                    select(func.count(ReservationItem.id)).where(
                        ReservationItem.device_id == device_id,
                        ReservationItem.reservation_date == target_date,
                    )
                )
                or 0
            )
            assert occupied_rows == 1
    finally:
        if app is not None:
            await dispose_app_redis(app)
        if engine is not None:
            await engine.dispose()
        await cleanup(prefix)
