from datetime import date, timedelta

import pytest
from app.api.v2.schemas import ReservationPlanRequest
from app.application.reservations import ReservationService
from app.auth.security import Principal
from app.core.errors import ApiError, unhandled_error_handler
from app.core.settings import Settings
from app.infrastructure.cache.rate_limit import (
    RateLimiter,
    RateLimitPolicy,
    enforce_login_rate_limit,
)
from fastapi import FastAPI, Request


class UnavailableRedis:
    async def eval(self, *_args: object) -> None:
        raise ConnectionError("redis is unavailable")


def make_request(app: FastAPI, path: str = "/api/v2/auth/login") -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.0"},
            "http_version": "1.1",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 1234),
            "scheme": "http",
            "method": "POST",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "app": app,
            "state": {},
        }
    )


@pytest.mark.asyncio
async def test_rate_limit_uses_local_fallback_and_returns_retry_after() -> None:
    app = FastAPI()
    app.state.settings = Settings(
        environment="test",
        cors_origins=[],
        rate_limit_login_capacity=1,
        rate_limit_login_refill_per_second=0.01,
    )
    app.state.redis_client = UnavailableRedis()

    request = make_request(app)
    policy = RateLimitPolicy("test", capacity=1, refill_per_second=0.01)
    limiter = RateLimiter(request)
    allowed, _, source = await limiter.allow(["ip:test"], policy)
    assert allowed is True
    assert source == "local"

    allowed, retry_after, source = await limiter.allow(["ip:test"], policy)
    assert allowed is False
    assert retry_after >= 1
    assert source == "local"

    login_request = make_request(app)
    await enforce_login_rate_limit(login_request, "admin")
    with pytest.raises(ApiError) as error:
        await enforce_login_rate_limit(login_request, "admin")
    assert error.value.status_code == 429
    assert error.value.headers["Retry-After"] == str(error.value.data["retry_after"])
    assert app.state.redis_circuit.allow() is False


@pytest.mark.asyncio
async def test_dependency_failure_is_exposed_as_structured_503() -> None:
    app = FastAPI()
    request = make_request(app, "/api/v2/ready")

    response = await unhandled_error_handler(request, OSError("database offline"))

    assert response.status_code == 503
    assert response.body is not None
    assert b"DEPENDENCY_UNAVAILABLE" in response.body


@pytest.mark.asyncio
async def test_reservation_cursor_returns_stable_keyset_pages(seeded) -> None:
    factory, _, _, student1, _, _, device, _ = seeded
    principal = Principal(
        user_id=student1.id,
        username=student1.username,
        college_id=student1.college_id,
        roles=("STUDENT",),
        token_type="access",
        token_id="cursor-test",
    )
    first_day = date.today() + timedelta(days=10)
    async with factory() as session:
        service = ReservationService(session, principal)
        for offset in range(3):
            await service.create(
                ReservationPlanRequest(
                    device_id=device.id,
                    start_date=first_day + timedelta(days=offset),
                    end_date=first_day + timedelta(days=offset),
                    purpose=f"游标分页测试 {offset}",
                ),
                idempotency_key=f"cursor-test-{offset}",
            )

    async with factory() as session:
        page_one = await ReservationService(session, principal).list_mine(
            page=1,
            page_size=2,
            cursor=10**9,
        )
        assert len(page_one.items) == 2
        assert page_one.has_more is True
        assert page_one.next_cursor is not None

        page_two = await ReservationService(session, principal).list_mine(
            page=1,
            page_size=2,
            cursor=page_one.next_cursor,
        )
        assert len(page_two.items) >= 1
        assert {item.id for item in page_one.items}.isdisjoint(
            {item.id for item in page_two.items}
        )
