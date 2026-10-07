from __future__ import annotations

import os
import secrets
from datetime import date, timedelta

import pytest
from app.core.settings import Settings
from app.infrastructure.cache.reservation_quota import (
    ReservationQuotaCache,
    ReservationQuotaReadiness,
)
from redis.asyncio import Redis


@pytest.mark.asyncio
async def test_real_redis_quota_prehold_readiness_and_idempotent_refund() -> None:
    if os.getenv("LAB_RUN_REDIS_INTEGRATION") != "1":
        pytest.skip("set LAB_RUN_REDIS_INTEGRATION=1 to test the configured Redis")

    settings = Settings()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    readiness = ReservationQuotaReadiness()
    cache = ReservationQuotaCache(redis, readiness=readiness)
    pool_id = secrets.randbelow(1_000_000_000) + 2_000_000_000
    device_ids = [pool_id + 1, pool_id + 2]
    first_date = date.today() + timedelta(days=60)
    dates = [first_date, first_date + timedelta(days=1)]
    token = f"42:{secrets.token_hex(12)}"
    invalidated_token = f"42:{secrets.token_hex(12)}"
    keys = [
        cache._quota_key(pool_id, current_date)
        for current_date in dates
    ]
    ready_keys = [
        cache._ready_key(pool_id, current_date)
        for current_date in dates
    ]
    marker = cache._marker_key(pool_id, token, "hold")
    invalidated_marker = cache._marker_key(pool_id, invalidated_token, "hold")
    availability = {
        dates[0]: {device_ids[0]: True, device_ids[1]: False},
        dates[1]: {device_ids[0]: False, device_ids[1]: True},
    }

    try:
        await redis.ping()
        disabled = await cache.reserve(pool_id, device_ids, dates, 1, token)
        assert disabled.status == "cache_miss"

        assert await cache.reconcile(pool_id, availability) is True
        readiness.ready = True
        discontinuous = await cache.reserve(pool_id, device_ids, dates, 1, token)
        assert discontinuous.status == "discontinuous"
        assert await redis.get(marker) is None

        common_availability = {
            current_date: {device_ids[0]: True, device_ids[1]: True}
            for current_date in dates
        }
        assert await cache.reconcile(pool_id, common_availability) is True
        reserved = await cache.reserve(pool_id, device_ids, dates, 1, token)
        assert reserved.status == "reserved"
        assert reserved.device_ids == (device_ids[0],)
        held_values = [await redis.hget(key, str(device_ids[0])) for key in keys]
        assert held_values == ["0", "0"]
        assert await cache.is_held(pool_id, token) is True

        duplicate = await cache.reserve(pool_id, device_ids, dates, 1, token)
        assert duplicate.status == "already_reserved"

        await cache.refund(pool_id, list(reserved.device_ids), dates, token)
        refunded_values = [await redis.hget(key, str(device_ids[0])) for key in keys]
        assert refunded_values == ["1", "1"]
        assert await redis.get(marker) == "REFUNDED"
        await cache.refund(pool_id, list(reserved.device_ids), dates, token)
        retried_refund_values = [await redis.hget(key, str(device_ids[0])) for key in keys]
        assert retried_refund_values == ["1", "1"]

        stale_hold = await cache.reserve(
            pool_id,
            device_ids,
            dates,
            1,
            invalidated_token,
        )
        assert stale_hold.status == "reserved"
        await cache.refund_and_invalidate(pool_id, dates, invalidated_token)
        quota_key_exists = [await redis.exists(key) for key in keys]
        ready_key_exists = [await redis.exists(key) for key in ready_keys]
        assert quota_key_exists == [0, 0]
        assert ready_key_exists == [0, 0]
        assert await redis.get(invalidated_marker) == "REFUNDED"
        assert readiness.ready is False
    finally:
        await redis.delete(*keys, *ready_keys, marker, invalidated_marker)
        await redis.aclose()
