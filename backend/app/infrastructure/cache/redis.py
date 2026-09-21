from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from contextlib import asynccontextmanager
from datetime import date
from time import monotonic
from uuid import uuid4

from fastapi import Request
from redis.asyncio import Redis, from_url
from redis.exceptions import RedisError

REDIS_ERRORS = (TimeoutError, OSError, ConnectionError, RedisError)


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


async def _release_locks(
    client: Redis,
    keys: list[str],
    token: str,
    circuit: RedisCircuitBreaker | None = None,
) -> None:
    if not keys:
        return
    script = (
        "for _, key in ipairs(KEYS) do "
        "if redis.call('get', key) == ARGV[1] then redis.call('del', key) end "
        "end return 1"
    )
    try:
        if circuit is None:
            await client.eval(script, len(keys), *keys, token)
        else:
            await redis_call(circuit, lambda: client.eval(script, len(keys), *keys, token))
    except (*REDIS_ERRORS, RedisCircuitOpen):
        # TTL remains the final cleanup mechanism if the release connection is
        # also unavailable. Tokens prevent deleting another owner's lock.
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
    token = uuid4().hex
    acquired: list[str] = []
    deadline = monotonic() + max(0.0, settings.reservation_lock_wait_seconds)
    try:
        for key in keys:
            while True:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    break
                try:

                    async def set_lock():
                        return await asyncio.wait_for(
                            client.set(
                                key,
                                token,
                                nx=True,
                                ex=settings.reservation_lock_ttl_seconds,
                            ),
                            timeout=min(
                                remaining,
                                max(0.05, settings.reservation_lock_poll_seconds),
                            ),
                        )

                    ok = await redis_call(circuit, set_lock)
                except (*REDIS_ERRORS, RedisCircuitOpen):
                    # Redis is an accelerator for contention control, not the
                    # source of truth.  A tripped circuit must take the same
                    # fail-open path as a connection error so the database
                    # unique reservation-day key can decide the winner.
                    break
                if ok:
                    acquired.append(key)
                    break
                await asyncio.sleep(min(settings.reservation_lock_poll_seconds, remaining))
            if key not in acquired:
                break
        locked = len(acquired) == len(keys)
    except (*REDIS_ERRORS, RedisCircuitOpen):
        locked = False

    metrics = getattr(request.app.state, "metrics", None)
    if metrics is not None:
        metrics.increment(
            "reservation_lock_total",
            labels={"result": "acquired" if locked else "fallback"},
        )
    if not locked:
        await _release_locks(client, acquired, token, circuit)
        acquired.clear()

    try:
        yield locked
    finally:
        if acquired:
            await _release_locks(client, acquired, token, circuit)


async def dispose_app_redis(app: object) -> None:
    state = getattr(app, "state", None)
    client = getattr(state, "redis_client", None)
    if client is not None:
        await client.aclose()
