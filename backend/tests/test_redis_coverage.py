from __future__ import annotations

import asyncio
from collections import deque
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import app.infrastructure.cache.redis as redis_module
import pytest
from app.core.settings import Settings
from app.infrastructure.cache.redis import (
    _RELEASE_RESERVATION_LOCK,
    _RENEW_RESERVATION_LOCKS,
    RedisCircuitBreaker,
    RedisCircuitOpen,
    _record_watchdog_result,
    _release_locks,
    _reservation_keys,
    _reservation_lock_owner,
    _reservation_lock_watchdog,
    dispose_app_redis,
    get_redis,
    get_redis_circuit,
    get_redis_for_app,
    redis_call,
    reservation_lock,
)


class ScriptedRedis:
    def __init__(self, *responses: object) -> None:
        self.responses = deque(responses)
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.acquisition_started = asyncio.Event()
        self.block_acquisition = False
        self.acquisition_count = 0
        self.close = AsyncMock()

    async def eval(self, script: str, numkeys: int, *args: object) -> object:
        self.calls.append((script, (numkeys, *args)))
        if script == _RELEASE_RESERVATION_LOCK:
            if self.responses:
                response = self.responses.popleft()
                if isinstance(response, Exception):
                    raise response
            return 1
        if script != _RENEW_RESERVATION_LOCKS and script != _RELEASE_RESERVATION_LOCK:
            self.acquisition_count += 1
            if self.block_acquisition and self.acquisition_count >= 2:
                self.acquisition_started.set()
                await asyncio.Event().wait()
        if not self.responses:
            return 1
        response = self.responses.popleft()
        if isinstance(response, Exception):
            raise response
        return response

    async def aclose(self) -> None:
        await self.close()


def fake_request(client: ScriptedRedis | None = None, **overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "environment": "test",
        "_env_file": None,
        "reservation_lock_wait_seconds": 0,
        "reservation_lock_poll_seconds": 0.01,
        "reservation_lock_ttl_seconds": 1,
        "redis_socket_timeout_seconds": 0.2,
    }
    values.update(overrides)
    settings = Settings(**values)
    state = SimpleNamespace(settings=settings)
    if client is not None:
        state.redis_client = client
    state.metrics = SimpleNamespace(increment=Mock())
    return SimpleNamespace(app=SimpleNamespace(state=state))


def test_circuit_breaker_fast_fails_allows_one_recovery_probe_and_resets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = 10.0
    monkeypatch.setattr(redis_module, "monotonic", lambda: clock)
    circuit = RedisCircuitBreaker(failure_threshold=2, recovery_seconds=3)
    assert circuit.allow()
    circuit.record_failure()
    assert circuit.allow()
    circuit.record_failure()
    assert not circuit.allow()

    clock = 14.0
    assert circuit.allow()
    assert not circuit.allow()
    circuit.record_failure()
    assert not circuit.allow()
    clock = 17.0
    assert circuit.allow()
    circuit.record_success()
    assert circuit.allow()
    assert circuit._failures == 0


@pytest.mark.asyncio
async def test_redis_call_records_success_failure_and_open_circuit() -> None:
    circuit = RedisCircuitBreaker(failure_threshold=1, recovery_seconds=1)
    assert await redis_call(circuit, lambda: asyncio.sleep(0, result="ok")) == "ok"

    async def fail() -> None:
        raise ConnectionError("redis unavailable")

    with pytest.raises(ConnectionError):
        await redis_call(circuit, fail)
    with pytest.raises(RedisCircuitOpen):
        await redis_call(circuit, lambda: asyncio.sleep(0, result="must not run"))


def test_redis_client_and_circuit_are_cached_per_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[tuple[str, dict[str, object]]] = []

    def from_url(url: str, **kwargs: object) -> object:
        client = object()
        created.append((url, kwargs))
        return client

    monkeypatch.setattr(redis_module, "from_url", from_url)
    app = SimpleNamespace(
        state=SimpleNamespace(
            settings=Settings(environment="test", _env_file=None, redis_url="redis://cache/8")
        )
    )
    first = get_redis_for_app(app)
    assert get_redis_for_app(app) is first
    assert get_redis(SimpleNamespace(app=app)) is first
    assert created == [
        (
            "redis://cache/8",
            {"decode_responses": True, "socket_connect_timeout": 0.5, "socket_timeout": 0.5},
        )
    ]

    circuit = get_redis_circuit(app)
    assert get_redis_circuit(app) is circuit
    no_settings = SimpleNamespace(state=SimpleNamespace(redis_circuit=circuit))
    assert get_redis_circuit(no_settings) is circuit
    assert circuit.failure_threshold == 3


@pytest.mark.asyncio
async def test_redis_disposal_closes_only_an_existing_client() -> None:
    client = ScriptedRedis()
    await dispose_app_redis(SimpleNamespace(state=SimpleNamespace(redis_client=client)))
    client.close.assert_awaited_once()
    await dispose_app_redis(SimpleNamespace(state=SimpleNamespace()))
    await dispose_app_redis(SimpleNamespace())


@pytest.mark.asyncio
async def test_lock_key_owner_and_optional_metrics_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    dates = [date(2026, 9, 29), date(2026, 9, 28), date(2026, 9, 29)]
    assert _reservation_keys(8, None) == ["lab:v2:reservation:device:8"]
    assert _reservation_keys(8, dates) == [
        "lab:v2:reservation:8:2026-09-28",
        "lab:v2:reservation:8:2026-09-29",
    ]

    request = fake_request()
    first_owner = _reservation_lock_owner(request)
    assert _reservation_lock_owner(request) == first_owner
    assert ":" in first_owner
    _record_watchdog_result(request, "renewed")
    request.app.state.metrics.increment.assert_called_once_with(
        "reservation_lock_watchdog_total",
        labels={"result": "renewed"},
    )

    monkeypatch.setattr(redis_module.asyncio, "current_task", lambda: None)
    no_task_owner = _reservation_lock_owner(request)
    assert no_task_owner.startswith(request.app.state.reservation_lock_client_id + ":")
    assert no_task_owner != _reservation_lock_owner(request)
    _record_watchdog_result(SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())), "lost")


@pytest.mark.asyncio
async def test_release_lock_skips_empty_keys_and_swallows_redis_failures() -> None:
    client = ScriptedRedis(ConnectionError("redis unavailable"))
    await _release_locks(client, [], "owner", 1000)
    assert client.calls == []
    await _release_locks(client, ["key"], "owner", 1000)
    assert client.calls[0][0] == _RELEASE_RESERVATION_LOCK

    circuit = RedisCircuitBreaker(failure_threshold=1, recovery_seconds=1)
    circuit.record_failure()
    await _release_locks(client, ["key"], "owner", 1000, circuit)


@pytest.mark.asyncio
async def test_watchdog_retries_transient_redis_errors_then_stops_when_lease_is_lost() -> None:
    client = ScriptedRedis(ConnectionError("transient"), 1, 0)
    request = fake_request(client)
    circuit = RedisCircuitBreaker(failure_threshold=3)
    await _reservation_lock_watchdog(request, client, circuit, ["key"], "owner", 1000)

    results = [
        call.kwargs["labels"]["result"]
        for call in request.app.state.metrics.increment.call_args_list
    ]
    assert results == ["error", "lost"]
    assert len(client.calls) == 3


@pytest.mark.asyncio
async def test_watchdog_stops_and_reports_unexpected_errors() -> None:
    client = ScriptedRedis(RuntimeError("unexpected script failure"))
    request = fake_request(client)
    await _reservation_lock_watchdog(
        request,
        client,
        RedisCircuitBreaker(),
        ["key"],
        "owner",
        1000,
    )
    request.app.state.metrics.increment.assert_called_once_with(
        "reservation_lock_watchdog_total",
        labels={"result": "error"},
    )


@pytest.mark.asyncio
async def test_reservation_lock_acquires_sorted_date_keys_and_releases_them() -> None:
    client = ScriptedRedis(1, 1)
    request = fake_request(client, reservation_lock_wait_seconds=0.2)
    dates = [date(2026, 9, 29), date(2026, 9, 28)]

    async with reservation_lock(request, 7, dates) as acquired:
        assert acquired is True
        assert [call[1][1] for call in client.calls[:2]] == [
            "lab:v2:reservation:7:2026-09-28",
            "lab:v2:reservation:7:2026-09-29",
        ]

    assert client.calls[-1][0] == _RELEASE_RESERVATION_LOCK
    request.app.state.metrics.increment.assert_any_call(
        "reservation_lock_total",
        labels={"result": "acquired"},
    )


@pytest.mark.asyncio
async def test_reservation_lock_uses_database_fallback_on_redis_failure_or_empty_dates() -> None:
    broken = ScriptedRedis(ConnectionError("redis unavailable"))
    request = fake_request(broken, reservation_lock_wait_seconds=0.2)
    async with reservation_lock(request, 3, [date(2026, 9, 28)]) as acquired:
        assert acquired is False
    request.app.state.metrics.increment.assert_any_call(
        "reservation_lock_total",
        labels={"result": "fallback"},
    )

    empty_client = ScriptedRedis()
    empty_request = fake_request(empty_client, reservation_lock_wait_seconds=0.2)
    async with reservation_lock(empty_request, 3, []) as acquired:
        assert acquired is False
    assert empty_client.calls == []


@pytest.mark.asyncio
async def test_reservation_lock_falls_back_when_wait_expires_or_contention_persists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    no_wait_client = ScriptedRedis()
    no_wait_request = fake_request(no_wait_client, reservation_lock_wait_seconds=0)
    no_wait_request.app.state.metrics = None
    async with reservation_lock(no_wait_request, 14, [date(2026, 9, 28)]) as acquired:
        assert acquired is False
    assert no_wait_client.calls == []

    contention_client = ScriptedRedis(0, 0, 0, 0, 0)
    contention_request = fake_request(
        contention_client,
        reservation_lock_wait_seconds=0.03,
        reservation_lock_poll_seconds=0.01,
    )
    async with reservation_lock(contention_request, 15, [date(2026, 9, 28)]) as acquired:
        assert acquired is False
    assert len(contention_client.calls) >= 2
    assert contention_request.app.state.metrics.increment.call_args.kwargs["labels"] == {
        "result": "fallback"
    }

    class RedisFailureDuringKeyIteration:
        def __iter__(self):
            raise ConnectionError("key generation failed")

    monkeypatch.setattr(
        redis_module,
        "_reservation_keys",
        lambda _device_id, _dates: RedisFailureDuringKeyIteration(),
    )
    outer_failure_request = fake_request(ScriptedRedis(), reservation_lock_wait_seconds=0.1)
    async with reservation_lock(outer_failure_request, 16, [date(2026, 9, 28)]) as acquired:
        assert acquired is False


@pytest.mark.asyncio
async def test_cancelled_multiday_lock_releases_the_acquired_prefix() -> None:
    client = ScriptedRedis(1)
    client.block_acquisition = True
    request = fake_request(client, reservation_lock_wait_seconds=5)
    operation = asyncio.create_task(
        reservation_lock(request, 11, [date(2026, 9, 28), date(2026, 9, 29)]).__aenter__()
    )
    await asyncio.wait_for(client.acquisition_started.wait(), timeout=1)
    operation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert any(script == _RELEASE_RESERVATION_LOCK for script, _ in client.calls)
