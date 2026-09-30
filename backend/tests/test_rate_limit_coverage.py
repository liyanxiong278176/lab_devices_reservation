from __future__ import annotations

from collections import deque

import pytest
from app.auth.security import Principal
from app.core.errors import ApiError
from app.core.settings import Settings
from app.infrastructure.cache.rate_limit import (
    RateLimiter,
    RateLimitPolicy,
    _client_ip,
    _LocalBucket,
    enforce_authenticated_rate_limit,
    enforce_login_rate_limit,
    enforce_registration_rate_limit,
    policy_for_request,
)
from fastapi import FastAPI, Request


class EvalRedis:
    def __init__(self, results: tuple[object, ...] = ()) -> None:
        self.results = deque(results)
        self.calls: list[tuple[object, ...]] = []

    async def eval(self, *args: object) -> object:
        self.calls.append(args)
        result = self.results.popleft() if self.results else [1, 0]
        if isinstance(result, Exception):
            raise result
        return result


class Metrics:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object] | None]] = []

    def increment(self, name: str, *, labels: dict[str, object] | None = None) -> None:
        self.calls.append((name, labels))


def _app(**overrides: object) -> FastAPI:
    values: dict[str, object] = {
        "environment": "test",
        "cors_origins": [],
        "rate_limit_enabled": True,
        "rate_limit_default_capacity": 1,
        "rate_limit_default_refill_per_second": 0.001,
        "rate_limit_login_ip_capacity": 5,
        "rate_limit_login_ip_refill_per_second": 0.001,
        "rate_limit_login_capacity": 1,
        "rate_limit_login_refill_per_second": 0.001,
        "rate_limit_register_ip_capacity": 5,
        "rate_limit_register_ip_refill_per_second": 0.001,
        "rate_limit_register_username_capacity": 1,
        "rate_limit_register_username_refill_per_second": 0.001,
        "rate_limit_local_max_entries": 2,
        "rate_limit_redis_timeout_seconds": 0.1,
    }
    values.update(overrides)
    settings = Settings(**values)
    app = FastAPI()
    app.state.settings = settings
    app.state.redis_client = EvalRedis()
    app.state.metrics = Metrics()
    return app


def _request(
    app: FastAPI,
    path: str,
    *,
    method: str = "POST",
    client: tuple[str, int] | None = ("127.0.0.1", 1234),
    headers: tuple[tuple[bytes, bytes], ...] = (),
) -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.0"},
            "http_version": "1.1",
            "server": ("testserver", 80),
            "client": client,
            "scheme": "http",
            "method": method,
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": list(headers),
            "app": app,
            "state": {},
        }
    )


def _principal() -> Principal:
    return Principal(
        user_id=23,
        username="rate-limit-user",
        college_id=7,
        roles=("STUDENT",),
        token_type="access",
        token_id="rate-limit-test",
        permissions=(),
    )


def test_request_policy_classification_covers_upload_and_default_routes() -> None:
    app = _app()
    expected = {
        "/api/v2/reservations/": "reservation",
        "/api/v2/repair-reports": "repair",
        "/api/v2/repair-uploads": "upload",
        "/api/v2/qualification-uploads": "upload",
        "/api/v2/devices/9/documents": "upload",
        "/api/v2/devices": "default",
    }
    for path, name in expected.items():
        assert policy_for_request(_request(app, path)).name == name
    assert policy_for_request(_request(app, "/api/v2/reservations", method="GET")).name == "default"


@pytest.mark.asyncio
async def test_redis_bucket_success_disabled_limits_and_local_eviction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app()
    redis = EvalRedis(([1, 0],))
    app.state.redis_client = redis
    request = _request(app, "/api/v2/action")
    limiter = RateLimiter(request)
    policy = RateLimitPolicy("sample", 4, 2.0)
    assert await limiter.allow(["one", "two"], policy) == (True, 0, "redis")
    assert redis.calls[0][1] == 2
    assert "lab:v2:rate:policy-v2:sample:one" in redis.calls[0]

    assert await limiter.allow([], policy) == (True, 0, "disabled")
    assert await limiter.allow(["one"], RateLimitPolicy("zero", 0, 1.0)) == (True, 0, "disabled")
    assert await limiter.allow(["one"], RateLimitPolicy("no-refill", 1, 0.0)) == (
        True,
        0,
        "disabled",
    )

    policy = RateLimitPolicy("local", 1, 1e-9)
    for key in ("a", "b", "c"):
        await limiter._allow_local([key], policy)
    assert len(limiter._local) == 2

    limiter._local["refilled"] = _LocalBucket(tokens=0.5, updated_at=100.0)
    monkeypatch.setattr("app.infrastructure.cache.rate_limit.monotonic", lambda: 101.0)
    allowed, _ = await limiter._allow_local(["refilled"], RateLimitPolicy("refill", 1, 1.0))
    assert allowed is True


@pytest.mark.asyncio
async def test_authenticated_limit_uses_redis_then_rejects_with_local_fallback() -> None:
    app = _app()
    actor = _principal()
    request = _request(app, "/api/v2/devices", method="GET")
    assert await enforce_authenticated_rate_limit(request, actor) == actor
    assert app.state.redis_client.calls

    app.state.redis_client = EvalRedis((ConnectionError("redis offline"),) * 8)
    request = _request(app, "/api/v2/devices", method="GET")
    await enforce_authenticated_rate_limit(request, actor)
    with pytest.raises(ApiError) as error:
        await enforce_authenticated_rate_limit(request, actor)
    assert error.value.status_code == 429
    assert error.value.headers["Retry-After"] == str(error.value.data["retry_after"])
    assert error.value.data["source"] == "local"
    assert any(name == "rate_limit_rejected_total" for name, _ in app.state.metrics.calls)

    del app.state.metrics
    with pytest.raises(ApiError):
        await enforce_authenticated_rate_limit(
            _request(app, "/api/v2/devices", method="GET"), actor
        )

    disabled = _app(rate_limit_enabled=False)
    assert (
        await enforce_authenticated_rate_limit(
            _request(disabled, "/api/v2/devices", method="GET"), actor
        )
        == actor
    )


@pytest.mark.asyncio
async def test_login_limit_rejects_normalized_username_and_disabled_policy() -> None:
    app = _app()
    app.state.redis_client = EvalRedis((ConnectionError("redis offline"),) * 8)
    request = _request(app, "/api/v2/auth/login")
    await enforce_login_rate_limit(request, "  User-One ")
    with pytest.raises(ApiError) as error:
        await enforce_login_rate_limit(_request(app, "/api/v2/auth/login"), "user-one")
    assert error.value.status_code == 429
    assert error.value.data["source"] == "local"

    disabled = _app(rate_limit_enabled=False)
    await enforce_login_rate_limit(_request(disabled, "/api/v2/auth/login"), "user-one")

    ip_limited = _app(rate_limit_login_ip_capacity=1)
    ip_limited.state.redis_client = EvalRedis((ConnectionError("redis offline"),) * 4)
    await enforce_login_rate_limit(_request(ip_limited, "/api/v2/auth/login"), "other-user")
    with pytest.raises(ApiError):
        await enforce_login_rate_limit(_request(ip_limited, "/api/v2/auth/login"), "another-user")
    assert ("rate_limit_rejected_total", {"policy": "login_ip"}) in ip_limited.state.metrics.calls


@pytest.mark.asyncio
async def test_registration_limit_rejects_username_and_disabled_policy() -> None:
    app = _app()
    app.state.redis_client = EvalRedis((ConnectionError("redis offline"),) * 8)
    await enforce_registration_rate_limit(_request(app, "/api/v2/auth/register"), "  New-User ")
    with pytest.raises(ApiError) as error:
        await enforce_registration_rate_limit(_request(app, "/api/v2/auth/register"), "new-user")
    assert error.value.status_code == 429
    assert error.value.data["source"] == "local"
    assert any(
        name == "rate_limit_rejected_total" and labels == {"policy": "register_username"}
        for name, labels in app.state.metrics.calls
    )

    disabled = _app(rate_limit_enabled=False)
    await enforce_registration_rate_limit(_request(disabled, "/api/v2/auth/register"), "new-user")


@pytest.mark.asyncio
async def test_client_ip_falls_back_to_peer_without_a_client_address() -> None:
    app = _app()
    request = _request(app, "/api/v2/action", client=None)
    assert request.client is None
    assert _client_ip(request) == "unknown"
