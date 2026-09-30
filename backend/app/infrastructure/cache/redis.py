from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable
from contextlib import asynccontextmanager, suppress
from datetime import date
from time import monotonic
from uuid import uuid4
from weakref import WeakKeyDictionary

from fastapi import Request
from redis.asyncio import Redis, from_url
from redis.exceptions import RedisError

REDIS_ERRORS = (TimeoutError, OSError, ConnectionError, RedisError)
_logger = logging.getLogger(__name__)

_ACQUIRE_RESERVATION_LOCK = """
local current = redis.call('get', KEYS[1])
if not current then
    redis.call('set', KEYS[1], ARGV[1] .. '|1', 'PX', ARGV[2])
    return 1
end
local owner, count = string.match(current, '^([^|]+)|(%d+)$')
if owner == ARGV[1] then
    redis.call('set', KEYS[1], owner .. '|' .. (tonumber(count) + 1), 'PX', ARGV[2])
    return 1
end
return 0
"""

_RELEASE_RESERVATION_LOCK = """
for _, key in ipairs(KEYS) do
    local current = redis.call('get', key)
    if current then
        local owner, count = string.match(current, '^([^|]+)|(%d+)$')
        if owner == ARGV[1] then
            count = tonumber(count)
            if count > 1 then
                redis.call('set', key, owner .. '|' .. (count - 1), 'PX', ARGV[2])
            else
                redis.call('del', key)
            end
        end
    end
end
return 1
"""

_RENEW_RESERVATION_LOCKS = """
for _, key in ipairs(KEYS) do
    local current = redis.call('get', key)
    if not current then
        return 0
    end
    local owner, count = string.match(current, '^([^|]+)|(%d+)$')
    if owner ~= ARGV[1] or not count then
        return 0
    end
end
for _, key in ipairs(KEYS) do
    redis.call('pexpire', key, ARGV[2])
end
return 1
"""


class RedisCircuitOpen(RuntimeError):
    """Raised when Redis is in the short fast-fail window."""


class RedisCircuitBreaker:
    """Small process-local circuit breaker for the non-authoritative Redis path."""

    def __init__(self, failure_threshold: int = 3, recovery_seconds: float = 5.0) -> None:
        self.failure_threshold = max(1, int(failure_threshold))
        self.recovery_seconds = max(0.1, float(recovery_seconds))
        self._failures = 0
        self._opened_at = 0.0
        self._probe_in_flight = False

    def allow(self) -> bool:
        if self._opened_at <= 0:
            return True
        if monotonic() - self._opened_at < self.recovery_seconds:
            return False
        if self._probe_in_flight:
            return False
        self._probe_in_flight = True
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = 0.0
        self._probe_in_flight = False

    def record_failure(self) -> None:
        self._probe_in_flight = False
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._opened_at = monotonic()


def get_redis_circuit(app: object) -> RedisCircuitBreaker:
    state = getattr(app, "state")
    circuit = getattr(state, "redis_circuit", None)
    if circuit is None:
        settings = state.settings
        circuit = RedisCircuitBreaker(
            failure_threshold=getattr(settings, "redis_circuit_failure_threshold", 3),
            recovery_seconds=getattr(settings, "redis_circuit_recovery_seconds", 5.0),
        )
        state.redis_circuit = circuit
    return circuit


async def redis_call[T](
    circuit: RedisCircuitBreaker,
    operation: Callable[[], Awaitable[T]],
) -> T:
    if not circuit.allow():
        raise RedisCircuitOpen("redis circuit is open")
    try:
        result = await operation()
    except REDIS_ERRORS:
        circuit.record_failure()
        raise
    else:
        circuit.record_success()
        return result


def _client_kwargs(app: object) -> dict[str, float]:
    settings = app.state.settings  # type: ignore[attr-defined]
    timeout = float(getattr(settings, "redis_socket_timeout_seconds", 0.5))
    return {"socket_connect_timeout": timeout, "socket_timeout": timeout}


def get_redis_for_app(app: object) -> Redis:
    state = getattr(app, "state")
    client = getattr(state, "redis_client", None)
    if client is None:
        client = from_url(
            state.settings.redis_url,
            decode_responses=True,
            **_client_kwargs(app),
        )
        state.redis_client = client
    return client


def get_redis(request: Request) -> Redis:
    return get_redis_for_app(request.app)


def _reservation_keys(device_id: int, dates: Iterable[date] | None) -> list[str]:
    if dates is None:
        # Backward-compatible device lock for callers that do not yet have a
        # parsed date set. The v2 HTTP create path always supplies dates.
        return [f"lab:v2:reservation:device:{device_id}"]
    unique_dates = sorted(set(dates))
    return [f"lab:v2:reservation:{device_id}:{item.isoformat()}" for item in unique_dates]


def _reservation_lock_owner(request: Request) -> str:
    """Return a stable lock owner for this app process and asyncio task."""

    state = request.app.state
    client_id = getattr(state, "reservation_lock_client_id", None)
    if client_id is None:
        client_id = uuid4().hex
        state.reservation_lock_client_id = client_id

    task = asyncio.current_task()
    if task is None:
        return f"{client_id}:{uuid4().hex}"

    task_owners = getattr(state, "reservation_lock_task_owners", None)
    if task_owners is None:
        task_owners = WeakKeyDictionary()
        state.reservation_lock_task_owners = task_owners
    task_owner = task_owners.get(task)
    if task_owner is None:
        task_owner = uuid4().hex
        task_owners[task] = task_owner
    return f"{client_id}:{task_owner}"


def _record_watchdog_result(request: Request, result: str) -> None:
    metrics = getattr(request.app.state, "metrics", None)
    if metrics is not None:
        metrics.increment("reservation_lock_watchdog_total", labels={"result": result})


async def _release_locks(
    client: Redis,
    keys: list[str],
    owner: str,
    lease_ttl_ms: int,
    circuit: RedisCircuitBreaker | None = None,
) -> None:
    if not keys:
        return
    try:
        if circuit is None:
            await client.eval(
                _RELEASE_RESERVATION_LOCK,
                len(keys),
                *keys,
                owner,
                lease_ttl_ms,
            )
        else:
            await redis_call(
                circuit,
                lambda: client.eval(
                    _RELEASE_RESERVATION_LOCK,
                    len(keys),
                    *keys,
                    owner,
                    lease_ttl_ms,
                ),
            )
    except (*REDIS_ERRORS, RedisCircuitOpen):
        # TTL remains the final cleanup mechanism if release is unavailable.
        return


async def _reservation_lock_watchdog(
    request: Request,
    client: Redis,
    circuit: RedisCircuitBreaker,
    keys: list[str],
    owner: str,
    lease_ttl_ms: int,
) -> None:
    interval = max(0.05, lease_ttl_ms / 3000)
    while True:
        await asyncio.sleep(interval)
        try:
            renewed = await redis_call(
                circuit,
                lambda: client.eval(
                    _RENEW_RESERVATION_LOCKS,
                    len(keys),
                    *keys,
                    owner,
                    lease_ttl_ms,
                ),
            )
        except (*REDIS_ERRORS, RedisCircuitOpen):
            _record_watchdog_result(request, "error")
            # A transient Redis failure should not permanently disable the
            # watchdog. Retry on the next interval; if the lease expires or
            # another owner replaces it, the Lua check below will stop renewals.
            continue
        except Exception:
            _logger.exception("Reservation lock watchdog stopped unexpectedly")
            _record_watchdog_result(request, "error")
            return

        if int(renewed) != 1:
            # A missing key or a different owner means this task has lost the
            # lease; never recreate it or overwrite the current holder.
            _record_watchdog_result(request, "lost")
            return


@asynccontextmanager
async def reservation_lock(
    request: Request,
    device_id: int,
    dates: Iterable[date] | None = None,
):
    """Best-effort date-level lock with a database uniqueness fallback.

    All date keys are acquired in sorted order. Redis only reduces database
    contention; v2_reservation_day's unique key remains authoritative when
    Redis is unavailable or the bounded wait expires.
    """

    settings = request.app.state.settings
    client = get_redis(request)
    circuit = get_redis_circuit(request.app)
    keys = _reservation_keys(device_id, dates)
    owner = _reservation_lock_owner(request)
    lease_ttl_ms = max(1, int(settings.reservation_lock_ttl_seconds)) * 1000
    acquired: list[str] = []
    deadline = monotonic() + max(0.0, settings.reservation_lock_wait_seconds)
    try:
        try:
            for key in keys:
                while True:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        break
                    try:

                        async def try_lock():
                            return await asyncio.wait_for(
                                client.eval(
                                    _ACQUIRE_RESERVATION_LOCK,
                                    1,
                                    key,
                                    owner,
                                    lease_ttl_ms,
                                ),
                                timeout=min(
                                    remaining,
                                    max(0.05, settings.reservation_lock_poll_seconds),
                                ),
                            )

                        ok = await redis_call(circuit, try_lock)
                    except (*REDIS_ERRORS, RedisCircuitOpen):
                        # Redis is an accelerator for contention control, not the
                        # source of truth. A tripped circuit takes the same
                        # fail-open path as a connection error so the database
                        # unique reservation-day key can decide the winner.
                        break
                    if int(ok) == 1:
                        acquired.append(key)
                        break
                    await asyncio.sleep(min(settings.reservation_lock_poll_seconds, remaining))
                if key not in acquired:
                    break
            locked = bool(keys) and len(acquired) == len(keys)
        except (*REDIS_ERRORS, RedisCircuitOpen):
            locked = False
    except asyncio.CancelledError:
        # Cancellation during multi-date acquisition must not strand the
        # already-acquired prefix until its TTL expires.
        await _release_locks(client, acquired, owner, lease_ttl_ms, circuit)
        raise

    metrics = getattr(request.app.state, "metrics", None)
    if metrics is not None:
        metrics.increment(
            "reservation_lock_total",
            labels={"result": "acquired" if locked else "fallback"},
        )
    if not locked:
        await _release_locks(client, acquired, owner, lease_ttl_ms, circuit)
        acquired.clear()

    watchdog_task = (
        asyncio.create_task(
            _reservation_lock_watchdog(
                request,
                client,
                circuit,
                keys,
                owner,
                lease_ttl_ms,
            ),
            name="reservation-lock-watchdog",
        )
        if locked
        else None
    )
    try:
        yield locked
    finally:
        if watchdog_task is not None:
            watchdog_task.cancel()
            with suppress(asyncio.CancelledError):
                await watchdog_task
        if acquired:
            await _release_locks(client, acquired, owner, lease_ttl_ms, circuit)


async def dispose_app_redis(app: object) -> None:
    state = getattr(app, "state", None)
    client = getattr(state, "redis_client", None)
    if client is not None:
        await client.aclose()
