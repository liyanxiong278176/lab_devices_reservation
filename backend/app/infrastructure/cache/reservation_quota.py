from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from redis.asyncio import Redis

from app.infrastructure.cache.redis import (
    REDIS_ERRORS,
    RedisCircuitBreaker,
    RedisCircuitOpen,
    redis_call,
)

_logger = logging.getLogger(__name__)
_BUSINESS_TZ = ZoneInfo("Asia/Shanghai")


@dataclass
class ReservationQuotaReadiness:
    """Process-wide gate: Redis preholds stay off until a MySQL rebuild finishes."""

    ready: bool = False
    generation: int = 0

    def disable(self) -> None:
        self.ready = False

    def invalidate_snapshot(self) -> None:
        self.generation += 1
        self.ready = False

    def record_mutation(self) -> None:
        self.generation += 1


def get_reservation_quota_readiness(app: object) -> ReservationQuotaReadiness:
    state = getattr(app, "state")
    readiness = getattr(state, "reservation_quota_readiness", None)
    if readiness is None:
        readiness = ReservationQuotaReadiness()
        state.reservation_quota_readiness = readiness
    return readiness

_RESERVE_QUOTA = """
local marker = KEYS[#KEYS]
local previous_state = redis.call('get', marker)
if previous_state and previous_state ~= 'UNKNOWN' and previous_state ~= 'DIRTY' then
    return {2}
end
if previous_state then
    redis.call('del', marker)
end
local quantity = tonumber(ARGV[1])
local marker_ttl = tonumber(ARGV[2])
local device_count = tonumber(ARGV[3])
local day_count = (#KEYS - 1) / 2
for day = 1, day_count do
    if redis.call('get', KEYS[day_count + day]) ~= '1' then
        return {-1}
    end
end
local available_by_day = {}
for day = 1, day_count do
    available_by_day[day] = 0
end
local selected = {}
for index = 1, device_count do
    local device_id = ARGV[index + 3]
    local available_for_all_days = true
    for day = 1, day_count do
        local value = redis.call('hget', KEYS[day], device_id)
        if not value or (value ~= '0' and value ~= '1') then
            return {-1}
        end
        if value == '1' then
            available_by_day[day] = available_by_day[day] + 1
        else
            available_for_all_days = false
        end
    end
    if available_for_all_days and #selected < quantity then
        selected[#selected + 1] = device_id
    end
end
if #selected < quantity then
    local each_day_has_capacity = true
    for day = 1, day_count do
        if available_by_day[day] < quantity then
            each_day_has_capacity = false
            break
        end
    end
    if each_day_has_capacity then
        return {3}
    end
    return {0}
end
for day = 1, day_count do
    for index = 1, #selected do
        redis.call('hset', KEYS[day], selected[index], '0')
    end
    redis.call('pexpire', KEYS[day], tonumber(ARGV[3 + device_count + day]))
end
redis.call('set', marker, 'HELD', 'PX', marker_ttl)
local result = {1}
for index = 1, #selected do
    result[#result + 1] = selected[index]
end
return result
"""

_FINALIZE_QUOTA = """
if redis.call('get', KEYS[1]) == 'HELD' then
    redis.call('set', KEYS[1], 'COMMITTED', 'PX', tonumber(ARGV[1]))
    return 1
end
return 0
"""

_MARK_REFUNDED_WITHOUT_HOLD = """
local state = redis.call('get', KEYS[1])
if state == 'HELD' or state == 'COMMITTED' then
    return 0
end
redis.call('set', KEYS[1], 'REFUNDED', 'PX', tonumber(ARGV[1]))
return 1
"""

_MARK_UNKNOWN_QUOTA = """
local marker = KEYS[#KEYS]
local state = redis.call('get', marker)
if state == 'HELD' or not state then
    redis.call('set', marker, 'UNKNOWN', 'PX', tonumber(ARGV[1]))
end
local day_count = (#KEYS - 1) / 2
for day = 1, day_count do
    redis.call('del', KEYS[day])
    redis.call('del', KEYS[day_count + day])
end
return 1
"""

_REFUND_QUOTA = """
local marker = KEYS[#KEYS]
if redis.call('get', marker) ~= 'HELD' then
    return 0
end
local day_count = (#KEYS - 1) / 2
local device_count = tonumber(ARGV[1])
for day = 1, day_count do
    if redis.call('get', KEYS[day_count + day]) ~= '1' then
        for invalid_day = 1, day_count do
            redis.call('del', KEYS[invalid_day])
            redis.call('del', KEYS[day_count + invalid_day])
        end
        redis.call('set', marker, 'DIRTY', 'PX', tonumber(ARGV[2 + device_count]))
        return -1
    end
    if redis.call('exists', KEYS[day]) == 0 then
        for invalid_day = 1, day_count do
            redis.call('del', KEYS[invalid_day])
            redis.call('del', KEYS[day_count + invalid_day])
        end
        redis.call('set', marker, 'DIRTY', 'PX', tonumber(ARGV[2 + device_count]))
        return -1
    end
    for index = 1, device_count do
        local device_id = ARGV[index + 1]
        if not redis.call('hget', KEYS[day], device_id) then
            for invalid_day = 1, day_count do
                redis.call('del', KEYS[invalid_day])
                redis.call('del', KEYS[day_count + invalid_day])
            end
            redis.call('set', marker, 'DIRTY', 'PX', tonumber(ARGV[2 + device_count]))
            return -1
        end
    end
end
for day = 1, day_count do
    for index = 1, device_count do
        redis.call('hset', KEYS[day], ARGV[index + 1], '1')
    end
    redis.call('pexpire', KEYS[day], tonumber(ARGV[2 + device_count + day]))
end
redis.call('set', marker, 'REFUNDED', 'PX', tonumber(ARGV[2 + device_count]))
return 1
"""

_REFUND_INVALIDATE_QUOTA = """
local marker = KEYS[#KEYS]
if redis.call('get', marker) ~= 'HELD' then
    return 0
end
local day_count = (#KEYS - 1) / 2
for day = 1, day_count do
    redis.call('del', KEYS[day])
    redis.call('del', KEYS[day_count + day])
end
redis.call('set', marker, 'REFUNDED', 'PX', tonumber(ARGV[1]))
return 1
"""

_RELEASE_QUOTA = """
local marker = KEYS[#KEYS]
if redis.call('exists', marker) == 1 then
    return 0
end
local device_count = tonumber(ARGV[1])
local day_count = (#KEYS - 1) / 2
for day = 1, day_count do
    if redis.call('get', KEYS[day_count + day]) ~= '1' then
        return -1
    end
    if redis.call('exists', KEYS[day]) == 0 then
        return -1
    end
    for index = 1, device_count do
        local device_id = ARGV[index + 1]
        if not redis.call('hget', KEYS[day], device_id) then
            return -1
        end
    end
end
for day = 1, day_count do
    for index = 1, device_count do
        redis.call('hset', KEYS[day], ARGV[index + 1], '1')
    end
    redis.call('pexpire', KEYS[day], tonumber(ARGV[2 + device_count + day]))
end
redis.call('set', marker, 'RELEASED', 'PX', tonumber(ARGV[2 + device_count]))
return 1
"""

ReserveStatus = Literal[
    "reserved",
    "already_reserved",
    "insufficient",
    "discontinuous",
    "cache_miss",
    "unavailable",
]


@dataclass(frozen=True)
class ReserveResult:
    status: ReserveStatus
    device_ids: tuple[int, ...] = ()


class ReservationQuotaCache:
    """Redis availability hints per physical device-day; MySQL remains authoritative."""

    def __init__(
        self,
        redis: Redis,
        circuit: RedisCircuitBreaker | None = None,
        readiness: ReservationQuotaReadiness | None = None,
    ) -> None:
        self.redis = redis
        self.circuit = circuit
        self.readiness = readiness

    @staticmethod
    def _quota_key(pool_id: int, day: date) -> str:
        # The pool hash tag keeps all dates for one pool in the same Redis Cluster slot.
        return f"reserve:quota:{{{pool_id}}}:{day.isoformat()}"

    @staticmethod
    def _ready_key(pool_id: int, day: date) -> str:
        return f"reserve:quota:{{{pool_id}}}:ready:{day.isoformat()}"

    @staticmethod
    def _marker_key(pool_id: int, token: str, purpose: str) -> str:
        safe_token = "".join(
            character
            for character in token
            if character.isalnum() or character in {"-", "_", ":"}
        )
        return f"reserve:quota:{{{pool_id}}}:op:{purpose}:{safe_token}"

    @staticmethod
    def _ttl_ms(day: date) -> int:
        now = datetime.now(UTC)
        expiry = datetime.combine(day + timedelta(days=2), time.min, tzinfo=_BUSINESS_TZ)
        return max(60_000, int((expiry.astimezone(UTC) - now).total_seconds() * 1000))

    async def _eval(self, script: str, keys: list[str], args: list[object]) -> object:
        async def operation():
            return await self.redis.eval(script, len(keys), *keys, *args)

        return await redis_call(self.circuit, operation) if self.circuit else await operation()

    async def reserve(
        self,
        pool_id: int,
        candidate_device_ids: list[int],
        dates: list[date],
        quantity: int,
        token: str,
    ) -> ReserveResult:
        ordered_dates = sorted(set(dates))
        device_ids = list(dict.fromkeys(candidate_device_ids))
        if not ordered_dates or quantity < 1 or not device_ids:
            return ReserveResult("cache_miss")
        if quantity > len(device_ids):
            return ReserveResult("insufficient")
        if self.readiness is not None and not self.readiness.ready:
            return ReserveResult("cache_miss")

        keys = [self._quota_key(pool_id, day) for day in ordered_dates]
        ready_keys = [self._ready_key(pool_id, day) for day in ordered_dates]
        marker = self._marker_key(pool_id, token, "hold")
        ttls = [self._ttl_ms(day) for day in ordered_dates]
        marker_ttl = 30 * 60 * 1000
        args: list[object] = [quantity, marker_ttl, len(device_ids), *device_ids, *ttls]
        try:
            raw = await self._eval(_RESERVE_QUOTA, [*keys, *ready_keys, marker], args)
        except (*REDIS_ERRORS, RedisCircuitOpen):
            if self.readiness is not None:
                self.readiness.disable()
            _logger.info("Reservation quota prehold bypassed because Redis is unavailable")
            return ReserveResult("unavailable")

        if not isinstance(raw, (list, tuple)) or not raw:
            return ReserveResult("cache_miss")
        code = int(raw[0])
        if code == 1:
            if self.readiness is not None:
                self.readiness.record_mutation()
            return ReserveResult("reserved", tuple(int(device_id) for device_id in raw[1:]))
        if code == 2:
            return ReserveResult("already_reserved")
        if code == 3:
            return ReserveResult("discontinuous")
        if code == 0:
            return ReserveResult("insufficient")
        return ReserveResult("cache_miss")

    async def is_held(self, pool_id: int, token: str) -> bool:
        """Fast path for duplicate in-flight tokens before MySQL unique-key wait."""
        if self.readiness is not None and not self.readiness.ready:
            return False
        marker = self._marker_key(pool_id, token, "hold")
        try:
            async def operation():
                return await self.redis.get(marker)

            state = (
                await redis_call(self.circuit, operation)
                if self.circuit
                else await operation()
            )
            return state == "HELD"
        except (*REDIS_ERRORS, RedisCircuitOpen):
            if self.readiness is not None:
                self.readiness.disable()
            return False

    async def finalize(self, pool_id: int, token: str) -> None:
        marker = self._marker_key(pool_id, token, "hold")
        try:
            result = int(
                await self._eval(_FINALIZE_QUOTA, [marker], [24 * 60 * 60 * 1000])
            )
            if result == 1 and self.readiness is not None:
                self.readiness.record_mutation()
        except (*REDIS_ERRORS, RedisCircuitOpen):
            if self.readiness is not None:
                self.readiness.disable()
            _logger.warning(
                "Could not finalize reservation quota prehold; reconciliation will repair it"
            )

    async def mark_refunded_without_hold(self, pool_id: int, token: str) -> None:
        """Persist a terminal failed attempt that never owned a Redis prehold."""
        marker = self._marker_key(pool_id, token, "hold")
        try:
            await self._eval(
                _MARK_REFUNDED_WITHOUT_HOLD,
                [marker],
                [24 * 60 * 60 * 1000],
            )
        except (*REDIS_ERRORS, RedisCircuitOpen):
            if self.readiness is not None:
                self.readiness.disable()
            _logger.warning("Could not mark reservation request refunded in Redis")

    async def mark_unknown(self, pool_id: int, dates: list[date], token: str) -> None:
        """Record an uncertain MySQL outcome and force quota reads back to MySQL."""
        if self.readiness is not None:
            self.readiness.invalidate_snapshot()
        keys = [self._quota_key(pool_id, day) for day in sorted(set(dates))]
        ready_keys = [self._ready_key(pool_id, day) for day in sorted(set(dates))]
        marker = self._marker_key(pool_id, token, "hold")
        try:
            await self._eval(
                _MARK_UNKNOWN_QUOTA,
                [*keys, *ready_keys, marker],
                [24 * 60 * 60 * 1000],
            )
        except (*REDIS_ERRORS, RedisCircuitOpen):
            if self.readiness is not None:
                self.readiness.invalidate_snapshot()
            _logger.warning(
                "Could not mark reservation quota outcome unknown; "
                "the marker will expire and reconciliation will rebuild quota keys"
            )

    async def refund(
        self,
        pool_id: int,
        device_ids: list[int],
        dates: list[date],
        token: str,
    ) -> None:
        ordered_dates = sorted(set(dates))
        ordered_devices = list(dict.fromkeys(device_ids))
        if not ordered_dates or not ordered_devices:
            return
        keys = [self._quota_key(pool_id, day) for day in ordered_dates]
        ready_keys = [self._ready_key(pool_id, day) for day in ordered_dates]
        marker = self._marker_key(pool_id, token, "hold")
        ttls = [self._ttl_ms(day) for day in ordered_dates]
        args: list[object] = [len(ordered_devices), *ordered_devices, 24 * 60 * 60 * 1000, *ttls]
        try:
            result = int(await self._eval(_REFUND_QUOTA, [*keys, *ready_keys, marker], args))
            if result == 1 and self.readiness is not None:
                self.readiness.record_mutation()
            if result < 0:
                if self.readiness is not None:
                    self.readiness.invalidate_snapshot()
                _logger.warning("Reservation quota refund found an expired or missing cache field")
        except (*REDIS_ERRORS, RedisCircuitOpen):
            if self.readiness is not None:
                self.readiness.invalidate_snapshot()
            _logger.warning("Reservation quota compensation failed; reconciliation will repair it")

    async def refund_and_invalidate(
        self,
        pool_id: int,
        dates: list[date],
        token: str,
    ) -> None:
        """End a failed hold without advertising a DB-conflicted device as free."""
        ordered_dates = sorted(set(dates))
        if not ordered_dates:
            return
        if self.readiness is not None:
            self.readiness.invalidate_snapshot()
        keys = [self._quota_key(pool_id, day) for day in ordered_dates]
        ready_keys = [self._ready_key(pool_id, day) for day in ordered_dates]
        marker = self._marker_key(pool_id, token, "hold")
        try:
            await self._eval(
                _REFUND_INVALIDATE_QUOTA,
                [*keys, *ready_keys, marker],
                [24 * 60 * 60 * 1000],
            )
        except (*REDIS_ERRORS, RedisCircuitOpen):
            if self.readiness is not None:
                self.readiness.invalidate_snapshot()
            _logger.warning(
                "Reservation quota invalidation after DB conflict failed; "
                "reconciliation will rebuild it"
            )

    async def release(
        self,
        pool_id: int,
        device_ids: list[int],
        dates: list[date],
        event_id: str,
    ) -> None:
        ordered_dates = sorted(set(dates))
        ordered_devices = list(dict.fromkeys(device_ids))
        if not ordered_dates or not ordered_devices:
            return
        keys = [self._quota_key(pool_id, day) for day in ordered_dates]
        ready_keys = [self._ready_key(pool_id, day) for day in ordered_dates]
        marker = self._marker_key(pool_id, event_id, "release")
        ttls = [self._ttl_ms(day) for day in ordered_dates]
        args: list[object] = [len(ordered_devices), *ordered_devices, 24 * 60 * 60 * 1000, *ttls]
        try:
            result = int(await self._eval(_RELEASE_QUOTA, [*keys, *ready_keys, marker], args))
            if result == 1 and self.readiness is not None:
                self.readiness.record_mutation()
            elif result < 0 and self.readiness is not None:
                self.readiness.invalidate_snapshot()
        except (*REDIS_ERRORS, RedisCircuitOpen):
            if self.readiness is not None:
                self.readiness.invalidate_snapshot()
            _logger.warning("Reservation quota release failed; reconciliation will repair it")

    async def prime(
        self,
        pool_id: int,
        available_by_date: dict[date, dict[int, bool]],
    ) -> None:
        if not available_by_date:
            return
        try:
            pipe = self.redis.pipeline(transaction=True)
            for day, availability in available_by_date.items():
                key = self._quota_key(pool_id, day)
                for device_id, available in availability.items():
                    pipe.hsetnx(key, str(device_id), "1" if available else "0")
                pipe.pexpire(key, self._ttl_ms(day))
            operation = pipe.execute
            if self.circuit:
                await redis_call(self.circuit, operation)
            else:
                await operation()
        except (*REDIS_ERRORS, RedisCircuitOpen):
            if self.readiness is not None:
                self.readiness.disable()
            _logger.debug("Could not warm reservation quota cache", exc_info=True)

    async def reconcile(
        self,
        pool_id: int,
        available_by_date: dict[date, dict[int, bool]],
        *,
        raise_errors: bool = False,
        track_mutation: bool = False,
    ) -> bool:
        """Overwrite Redis device-day hashes from the MySQL occupancy snapshot."""
        if not available_by_date:
            return True
        try:
            pipe = self.redis.pipeline(transaction=True)
            for day, availability in available_by_date.items():
                key = self._quota_key(pool_id, day)
                ready_key = self._ready_key(pool_id, day)
                pipe.delete(key)
                if availability:
                    pipe.hset(
                        key,
                        mapping={
                            str(device_id): "1" if available else "0"
                            for device_id, available in availability.items()
                        },
                    )
                    pipe.pexpire(key, self._ttl_ms(day))
                pipe.set(ready_key, "1", px=self._ttl_ms(day))
            operation = pipe.execute
            if self.circuit:
                await redis_call(self.circuit, operation)
            else:
                await operation()
            if track_mutation and self.readiness is not None:
                self.readiness.record_mutation()
            return True
        except (*REDIS_ERRORS, RedisCircuitOpen):
            if self.readiness is not None:
                self.readiness.disable()
            _logger.debug("Could not reconcile reservation quota cache", exc_info=True)
            if raise_errors:
                raise
            return False

    async def invalidate(self, pool_id: int, dates: list[date]) -> None:
        ordered_dates = sorted(set(dates))
        keys = [self._quota_key(pool_id, day) for day in ordered_dates]
        keys.extend(self._ready_key(pool_id, day) for day in ordered_dates)
        if not keys:
            return
        if self.readiness is not None:
            self.readiness.invalidate_snapshot()
        try:

            async def operation():
                return await self.redis.delete(*keys)

            if self.circuit:
                await redis_call(self.circuit, operation)
            else:
                await operation()
        except (*REDIS_ERRORS, RedisCircuitOpen):
            _logger.debug("Could not invalidate reservation quota cache", exc_info=True)
