from __future__ import annotations

import asyncio
import hashlib
import math
from dataclasses import dataclass
from time import monotonic, time

from fastapi import Depends, Request

from app.auth.security import Principal, get_current_principal
from app.core.errors import ApiError
from app.infrastructure.cache.redis import (
    REDIS_ERRORS,
    RedisCircuitOpen,
    get_redis,
    get_redis_circuit,
    redis_call,
)


@dataclass(frozen=True)
class RateLimitPolicy:
    name: str
    capacity: int
    refill_per_second: float


@dataclass
class _LocalBucket:
    tokens: float
    updated_at: float


TOKEN_BUCKET_SCRIPT = """
local now = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local refill = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])
local tokens = {}
local retry_after = 0
local allowed = 1

for i, key in ipairs(KEYS) do
  local current = tonumber(redis.call('HGET', key, 'tokens') or capacity)
  local updated = tonumber(redis.call('HGET', key, 'updated') or now)
  current = math.min(capacity, current + math.max(0, (now - updated) / 1000) * refill)
  tokens[i] = current
  if current < cost then
    allowed = 0
    if refill > 0 then
      retry_after = math.max(retry_after, math.ceil((cost - current) / refill))
    end
  end
end

if allowed == 1 then
  for i, key in ipairs(KEYS) do
    redis.call('HSET', key, 'tokens', tokens[i] - cost, 'updated', now)
    redis.call('EXPIRE', key, ttl)
  end
end
return {allowed, retry_after}
"""


class RateLimiter:
    def __init__(self, request: Request) -> None:
        self.request = request
        self.settings = request.app.state.settings
        self.redis = get_redis(request)
        self.circuit = get_redis_circuit(request.app)
        self._local: dict[str, _LocalBucket] = getattr(
            request.app.state,
            "local_rate_limit_buckets",
            {},
        )
        request.app.state.local_rate_limit_buckets = self._local
        self._local_lock: asyncio.Lock = getattr(
            request.app.state,
            "local_rate_limit_lock",
            asyncio.Lock(),
        )
        request.app.state.local_rate_limit_lock = self._local_lock

    async def allow(self, keys: list[str], policy: RateLimitPolicy) -> tuple[bool, int, str]:
        if not keys or policy.capacity <= 0 or policy.refill_per_second <= 0:
            return True, 0, "disabled"
        try:

            async def eval_bucket():
                return await asyncio.wait_for(
                    self.redis.eval(
                        TOKEN_BUCKET_SCRIPT,
                        len(keys),
                        *[f"lab:v2:rate:{key}" for key in keys],
                        int(time() * 1000),
                        policy.capacity,
                        policy.refill_per_second,
                        1,
                        max(60, math.ceil(policy.capacity / policy.refill_per_second * 2)),
                    ),
                    timeout=float(self.settings.rate_limit_redis_timeout_seconds),
                )

            result = await redis_call(self.circuit, eval_bucket)
            return bool(int(result[0])), int(result[1]), "redis"
        except (*REDIS_ERRORS, RedisCircuitOpen):
            self._metric("rate_limit_fallback_total", labels={"policy": policy.name})
            allowed, retry = await self._allow_local(keys, policy)
            return allowed, retry, "local"

    async def _allow_local(self, keys: list[str], policy: RateLimitPolicy) -> tuple[bool, int]:
        now = monotonic()
        async with self._local_lock:
            states: list[tuple[str, float]] = []
            retry_after = 0
            allowed = True
            for key in keys:
                state = self._local.get(key)
                tokens = (
                    policy.capacity
                    if state is None
                    else min(
                        policy.capacity,
                        state.tokens + max(0.0, now - state.updated_at) * policy.refill_per_second,
                    )
                )
                states.append((key, tokens))
                if tokens < 1:
                    allowed = False
                    retry_after = max(
                        retry_after,
                        math.ceil((1 - tokens) / policy.refill_per_second),
                    )
            if allowed:
                for key, tokens in states:
                    self._local[key] = _LocalBucket(tokens=tokens - 1, updated_at=now)
            if len(self._local) > int(self.settings.rate_limit_local_max_entries):
                oldest = sorted(self._local.items(), key=lambda item: item[1].updated_at)
                for key, _ in oldest[: max(1, len(oldest) // 10)]:
                    self._local.pop(key, None)
            return allowed, retry_after

    def _metric(self, name: str, labels: dict[str, object] | None = None) -> None:
        metrics = getattr(self.request.app.state, "metrics", None)
        if metrics is not None:
            metrics.increment(name, labels=labels)


def policy_for_request(request: Request) -> RateLimitPolicy:
    settings = request.app.state.settings
    path = request.url.path
    if request.method == "POST" and path.rstrip("/").endswith("/reservations"):
        return RateLimitPolicy(
            "reservation",
            settings.rate_limit_reservation_capacity,
            settings.rate_limit_reservation_refill_per_second,
        )
    if request.method == "POST" and "/repair-reports" in path:
        return RateLimitPolicy(
            "repair",
            settings.rate_limit_repair_capacity,
            settings.rate_limit_repair_refill_per_second,
        )
    return RateLimitPolicy(
        "default",
        settings.rate_limit_default_capacity,
        settings.rate_limit_default_refill_per_second,
    )


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def enforce_authenticated_rate_limit(
    request: Request,
    principal: Principal = Depends(get_current_principal),
) -> Principal:
    if not request.app.state.settings.rate_limit_enabled:
        return principal
    policy = policy_for_request(request)
    keys = [
        f"ip:{_client_ip(request)}:{policy.name}",
        f"user:{principal.user_id}:{policy.name}",
        f"college:{principal.college_id or 'global'}:{policy.name}",
    ]
    allowed, retry_after, source = await RateLimiter(request).allow(keys, policy)
    if not allowed:
        metrics = getattr(request.app.state, "metrics", None)
        if metrics is not None:
            metrics.increment("rate_limit_rejected_total", labels={"policy": policy.name})
        retry_after = max(1, retry_after)
        raise ApiError(
            "RATE_LIMITED",
            "请求过于频繁，请稍后再试",
            429,
            data={"retry_after": retry_after, "source": source},
            headers={"Retry-After": str(retry_after)},
        )
    return principal


async def enforce_login_rate_limit(request: Request, username: str) -> None:
    if not request.app.state.settings.rate_limit_enabled:
        return
    settings = request.app.state.settings
    policy = RateLimitPolicy(
        "login",
        settings.rate_limit_login_capacity,
        settings.rate_limit_login_refill_per_second,
    )
    username_key = hashlib.sha256(username.strip().lower().encode()).hexdigest()[:24]
    keys = [
        f"ip:{_client_ip(request)}:login",
        f"username:{username_key}:login",
    ]
    allowed, retry_after, source = await RateLimiter(request).allow(keys, policy)
    if not allowed:
        metrics = getattr(request.app.state, "metrics", None)
        if metrics is not None:
            metrics.increment("rate_limit_rejected_total", labels={"policy": "login"})
        retry_after = max(1, retry_after)
        raise ApiError(
            "RATE_LIMITED",
            "登录尝试过于频繁，请稍后再试",
            429,
            data={"retry_after": retry_after, "source": source},
            headers={"Retry-After": str(retry_after)},
        )
