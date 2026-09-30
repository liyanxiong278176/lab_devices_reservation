from __future__ import annotations

import asyncio
import json
import random
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from redis.asyncio import Redis

from app.infrastructure.cache.redis import (
    REDIS_ERRORS,
    RedisCircuitBreaker,
    RedisCircuitOpen,
    redis_call,
)


class CacheService:
    """Cache-Aside helper with jitter, hot-key protection and fail-open reads."""

    def __init__(
        self,
        redis: Redis,
        settings: object,
        metrics: object | None = None,
        circuit: RedisCircuitBreaker | None = None,
    ) -> None:
        self.redis = redis
        self.settings = settings
        self.metrics = metrics
        self.circuit = circuit

    async def _call(self, operation: Callable[[], Awaitable[Any]]) -> Any:
        if self.circuit is None:
            return await operation()
        return await redis_call(self.circuit, operation)

    def _ttl(self, base: int, *, negative: bool = False) -> int:
        minimum = max(5, int(getattr(self.settings, "cache_negative_ttl_seconds", 30)))
        if negative:
            return minimum
        jitter = max(0, int(getattr(self.settings, "cache_ttl_jitter_seconds", 60)))
        return max(30, int(base) + (random.randint(0, jitter) if jitter else 0))

    async def get_json(self, key: str) -> Any | None:
        try:
            raw = await self._call(lambda: self.redis.get(key))
            if raw is None:
                self._metric("cache_misses_total")
                return None
            self._metric("cache_hits_total")
            return json.loads(raw)
        except (ValueError, TypeError, *REDIS_ERRORS, RedisCircuitOpen):
            self._metric("cache_errors_total")
            return None

    async def set_json(
        self,
        key: str,
        value: Any,
        *,
        ttl_seconds: int | None = None,
        negative: bool = False,
    ) -> bool:
        try:
            ttl = self._ttl(
                ttl_seconds or int(getattr(self.settings, "cache_default_ttl_seconds", 300)),
                negative=negative,
            )
            encoded = json.dumps(value, ensure_ascii=False)
            await self._call(lambda: self.redis.set(key, encoded, ex=ttl))
            return True
        except (TypeError, ValueError, *REDIS_ERRORS, RedisCircuitOpen):
            self._metric("cache_errors_total")
            return False

    async def delete(self, *keys: str) -> bool:
        if not keys:
            return True
        try:
            await self._call(lambda: self.redis.delete(*keys))
            return True
        except (*REDIS_ERRORS, RedisCircuitOpen):
            self._metric("cache_errors_total")
            return False

    async def version(self, scope: str) -> int:
        key = f"lab:v2:cache:catalog:version:{scope}"
        try:
            value = await self._call(lambda: self.redis.get(key))
            if value is None:
                await self._call(lambda: self.redis.set(key, "1", nx=True))
                return 1
            return max(1, int(value))
        except (ValueError, TypeError, *REDIS_ERRORS, RedisCircuitOpen):
            self._metric("cache_errors_total")
            raise

    async def bump_version(self, scope: str) -> bool:
        key = f"lab:v2:cache:catalog:version:{scope}"
        try:
            await self._call(lambda: self.redis.incr(key))
            # The scope includes a college ID; export only its bounded kind.
            self._metric(
                "cache_invalidations_total",
                labels={"scope": scope.split(":", maxsplit=1)[0]},
            )
            return True
        except (*REDIS_ERRORS, RedisCircuitOpen):
            self._metric("cache_errors_total")
            raise

    async def get_or_set_json(
        self,
        key: str,
        loader: Callable[[], Awaitable[Any]],
        *,
        ttl_seconds: int | None = None,
        negative: bool = False,
    ) -> Any:
        cached = await self.get_json(key)
        if cached is not None:
            return cached

        lock_key = f"{key}:load-lock"
        token = uuid4().hex
        acquired = False
        try:
            acquired = bool(
                await self._call(
                    lambda: self.redis.set(
                        lock_key,
                        token,
                        nx=True,
                        ex=max(1, int(getattr(self.settings, "cache_hot_key_lock_seconds", 3))),
                    )
                )
            )
        except RedisCircuitOpen:
            self._metric("cache_errors_total")
            return await loader()
        except REDIS_ERRORS:
            self._metric("cache_errors_total")

        if acquired:
            try:
                cached = await self.get_json(key)
                if cached is not None:
                    return cached
                value = await loader()
                await self.set_json(key, value, ttl_seconds=ttl_seconds, negative=negative)
                return value
            finally:
                try:
                    await self._call(
                        lambda: self.redis.eval(
                            "if redis.call('get', KEYS[1]) == ARGV[1] then "
                            "return redis.call('del', KEYS[1]) else return 0 end",
                            1,
                            lock_key,
                            token,
                        )
                    )
                except (*REDIS_ERRORS, RedisCircuitOpen):
                    pass

        # A competing loader is already filling the key. Give it a short
        # chance, then fall back to the database rather than blocking traffic.
        await asyncio.sleep(float(getattr(self.settings, "cache_hot_key_wait_seconds", 0.5)))
        cached = await self.get_json(key)
        return cached if cached is not None else await loader()

    def _metric(self, name: str, labels: dict[str, object] | None = None) -> None:
        if self.metrics is not None:
            self.metrics.increment(name, labels=labels)


@asynccontextmanager
async def cache_dependency(
    redis: Redis,
    settings: object,
    metrics: object | None = None,
    circuit: RedisCircuitBreaker | None = None,
):
    yield CacheService(redis, settings, metrics, circuit)
