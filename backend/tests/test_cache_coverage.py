from __future__ import annotations

from collections import deque
from types import SimpleNamespace
from unittest.mock import Mock

import app.infrastructure.cache.cache as cache_module
import pytest
from app.infrastructure.cache.cache import CacheService, cache_dependency
from app.infrastructure.cache.redis import RedisCircuitBreaker


class FakeCacheRedis:
    def __init__(
        self,
        *,
        gets: tuple[object, ...] = (),
        sets: tuple[object, ...] = (),
        deletes: tuple[object, ...] = (),
        increments: tuple[object, ...] = (),
        evals: tuple[object, ...] = (),
    ) -> None:
        self.gets = deque(gets)
        self.sets = deque(sets)
        self.deletes = deque(deletes)
        self.increments = deque(increments)
        self.evals = deque(evals)
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    @staticmethod
    def _next(queue: deque[object], default: object) -> object:
        result = queue.popleft() if queue else default
        if isinstance(result, Exception):
            raise result
        return result

    async def get(self, key: str) -> object:
        self.calls.append(("get", (key,), {}))
        return self._next(self.gets, None)

    async def set(self, key: str, value: str, **kwargs: object) -> object:
        self.calls.append(("set", (key, value), kwargs))
        return self._next(self.sets, True)

    async def delete(self, *keys: str) -> object:
        self.calls.append(("delete", keys, {}))
        return self._next(self.deletes, 1)

    async def incr(self, key: str) -> object:
        self.calls.append(("incr", (key,), {}))
        return self._next(self.increments, 2)

    async def eval(self, script: str, numkeys: int, *args: object) -> object:
        self.calls.append(("eval", (script, numkeys, *args), {}))
        return self._next(self.evals, 1)


def settings(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "cache_negative_ttl_seconds": 2,
        "cache_ttl_jitter_seconds": 4,
        "cache_default_ttl_seconds": 60,
        "cache_hot_key_lock_seconds": 3,
        "cache_hot_key_wait_seconds": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def service(
    redis: FakeCacheRedis,
    *,
    config: SimpleNamespace | None = None,
    metrics: Mock | None = None,
    circuit: RedisCircuitBreaker | None = None,
) -> CacheService:
    return CacheService(redis, config or settings(), metrics, circuit)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_cache_get_json_hit_miss_decode_failure_and_redis_failure() -> None:
    metrics = Mock()
    redis = FakeCacheRedis(gets=('{"name":"设备"}', None, "{", ConnectionError("offline")))
    cache = service(redis, metrics=metrics)

    assert await cache.get_json("item") == {"name": "设备"}
    assert await cache.get_json("missing") is None
    assert await cache.get_json("invalid-json") is None
    assert await cache.get_json("unavailable") is None
    assert [call.args[0] for call in metrics.increment.call_args_list] == [
        "cache_hits_total",
        "cache_misses_total",
        "cache_hits_total",
        "cache_errors_total",
        "cache_errors_total",
    ]


@pytest.mark.asyncio
async def test_cache_ttl_negative_entries_serialization_and_write_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cache_module.random, "randint", lambda low, high: high)
    redis = FakeCacheRedis(sets=(True, True, ConnectionError("offline")))
    cache = service(redis)

    assert cache._ttl(20) == 30
    assert cache._ttl(200, negative=True) == 5
    assert cache._ttl(80, negative=True) == 5
    assert await cache.set_json("normal", {"value": "值"}, ttl_seconds=20)
    assert redis.calls[-1][2] == {"ex": 30}
    assert await cache.set_json("negative", None, negative=True)
    assert redis.calls[-1][2] == {"ex": 5}
    assert not await cache.set_json("bad-object", object())
    assert not await cache.set_json("unavailable", {"value": 1})


@pytest.mark.asyncio
async def test_cache_delete_handles_empty_keys_success_and_backend_error() -> None:
    metrics = Mock()
    cache = service(FakeCacheRedis(), metrics=metrics)
    assert await cache.delete()
    assert await cache.delete("a", "b") is True
    failed = service(FakeCacheRedis(deletes=(ConnectionError("offline"),)), metrics=metrics)
    assert await failed.delete("a", "b") is False
    metrics.increment.assert_called_once_with("cache_errors_total", labels=None)


@pytest.mark.asyncio
async def test_cache_version_initialization_clamping_and_failures() -> None:
    redis = FakeCacheRedis(gets=(None, "0", "not-an-int", ConnectionError("offline")))
    cache = service(redis, metrics=Mock())
    assert await cache.version("device:7") == 1
    assert redis.calls[1][0] == "set"
    assert redis.calls[1][2] == {"nx": True}
    assert await cache.version("device:7") == 1
    with pytest.raises(ValueError):
        await cache.version("broken")
    with pytest.raises(ConnectionError):
        await cache.version("offline")


@pytest.mark.asyncio
async def test_cache_bump_version_reports_bounded_scope_and_propagates_failures() -> None:
    metrics = Mock()
    cache = service(FakeCacheRedis(increments=(3, ConnectionError("offline"))), metrics=metrics)
    assert await cache.bump_version("college:91827")
    metrics.increment.assert_called_once_with(
        "cache_invalidations_total",
        labels={"scope": "college"},
    )
    with pytest.raises(ConnectionError):
        await cache.bump_version("college:91827")
    assert metrics.increment.call_args_list[-1].args[0] == "cache_errors_total"


@pytest.mark.asyncio
async def test_get_or_set_handles_hit_double_check_loader_and_loader_error() -> None:
    hit = service(FakeCacheRedis(gets=('{"cached":true}',)))
    assert await hit.get_or_set_json("hit", lambda: _unexpected_loader()) == {"cached": True}

    double_checked = service(
        FakeCacheRedis(
            gets=(None, '{"raced":true}'),
            sets=(True,),
        )
    )
    assert await double_checked.get_or_set_json("double", lambda: _unexpected_loader()) == {
        "raced": True
    }

    loader_calls = 0

    async def loader() -> dict[str, int]:
        nonlocal loader_calls
        loader_calls += 1
        return {"loaded": 1}

    loaded_redis = FakeCacheRedis(gets=(None, None), sets=(True, True))
    loaded = service(loaded_redis)
    assert await loaded.get_or_set_json("loaded", loader, ttl_seconds=10) == {"loaded": 1}
    assert loader_calls == 1
    assert [item[0] for item in loaded_redis.calls] == ["get", "set", "get", "set", "eval"]

    async def broken_loader() -> object:
        raise RuntimeError("database unavailable")

    error_cache = service(FakeCacheRedis(gets=(None, None), sets=(True,)))
    with pytest.raises(RuntimeError, match="database unavailable"):
        await error_cache.get_or_set_json("broken", broken_loader)
    assert error_cache.redis.calls[-1][0] == "eval"

    cleanup_failure = service(
        FakeCacheRedis(gets=(None, None), sets=(True, True), evals=(ConnectionError("offline"),))
    )
    cleanup_result = await cleanup_failure.get_or_set_json(
        "cleanup",
        lambda: _return_value("loaded"),
    )
    assert cleanup_result == "loaded"


@pytest.mark.asyncio
async def test_get_or_set_handles_open_circuit_lock_failure_and_competing_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metrics = Mock()
    circuit = RedisCircuitBreaker(failure_threshold=1)
    circuit.record_failure()
    open_cache = service(FakeCacheRedis(), metrics=metrics, circuit=circuit)
    assert await open_cache.get_or_set_json("open", lambda: _return_value("db")) == "db"
    metrics.increment.assert_called_with("cache_errors_total", labels=None)

    failed_lock = service(
        FakeCacheRedis(gets=(None, None), sets=(ConnectionError("lock unavailable"),)),
        metrics=Mock(),
    )
    assert await failed_lock.get_or_set_json("failed-lock", lambda: _return_value("db")) == "db"

    cached_after_wait = service(
        FakeCacheRedis(gets=(None, '{"winner":true}'), sets=(None,)),
        config=settings(cache_hot_key_wait_seconds=0),
    )
    assert await cached_after_wait.get_or_set_json("contended", lambda: _unexpected_loader()) == {
        "winner": True
    }

    fallback_after_wait = service(
        FakeCacheRedis(gets=(None, None), sets=(None,)),
        config=settings(cache_hot_key_wait_seconds=0),
    )
    assert await fallback_after_wait.get_or_set_json(
        "contended-miss", lambda: _return_value("database")
    ) == "database"

    monkeypatch.setattr(cache_module, "uuid4", lambda: SimpleNamespace(hex="stable-token"))
    assert [item[0] for item in cached_after_wait.redis.calls if item[0] == "set"]


@pytest.mark.asyncio
async def test_cache_dependency_yields_service_and_metrics_are_optional() -> None:
    context = cache_dependency(FakeCacheRedis(), settings(), None, None)
    async with context as cache:
        assert isinstance(cache, CacheService)
        assert await cache.delete() is True
        cache._metric("not-recorded")


async def _unexpected_loader() -> object:
    raise AssertionError("loader must not run for a cache hit")


async def _return_value(value: object) -> object:
    return value
