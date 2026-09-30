"""Verify lock degradation uses real ReservationService + MySQL, and auth fails closed."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "qa_eval"))

from app.api.v2.schemas import ReservationPlanRequest  # noqa: E402
from app.application.reservations import ReservationService  # noqa: E402
from app.auth.security import Principal, create_access_token, resolve_principal  # noqa: E402
from app.core.errors import ApiError  # noqa: E402
from app.core.settings import Settings  # noqa: E402
from app.infrastructure.cache.redis import dispose_app_redis, reservation_lock  # noqa: E402
from app.infrastructure.db import models  # noqa: E402
from config import FIXTURE_FILE, RESULTS, require_mysql_dsn  # noqa: E402


class Metrics:
    def __init__(self) -> None:
        self.counts: dict[tuple[str, str], int] = {}

    def increment(self, name: str, labels: dict[str, object] | None = None) -> None:
        result = str((labels or {}).get("result", ""))
        key = (name, result)
        self.counts[key] = self.counts.get(key, 0) + 1


def make_request(app: FastAPI, path: str = "/api/v2/reservations") -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 54321),
            "server": ("127.0.0.1", 8000),
            "app": app,
        }
    )


async def run() -> dict[str, Any]:
    manifest = json.loads(FIXTURE_FILE.read_text(encoding="utf-8"))
    engine = create_async_engine(
        require_mysql_dsn(), pool_size=4, max_overflow=4, pool_pre_ping=True
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = FastAPI()
    app.state.settings = Settings(
        _env_file=None,
        mysql_dsn=require_mysql_dsn(),
        redis_url="redis://127.0.0.1:6399/15",
        redis_socket_timeout_seconds=0.1,
        redis_circuit_failure_threshold=1,
        redis_circuit_recovery_seconds=0.1,
        reservation_lock_ttl_seconds=2,
        reservation_lock_wait_seconds=0.25,
        reservation_lock_poll_seconds=0.05,
    )
    app.state.metrics = Metrics()
    device_id = manifest["device_ids"]["CSE"][1]
    day = date.today() + timedelta(days=14)
    accounts = manifest["accounts"]["students"]["CSE"][:2]

    async def submit(index: int) -> dict[str, Any]:
        user = accounts[index]
        principal = Principal(
            user_id=int(user["user_id"]),
            username=str(user["username"]),
            college_id=int(manifest["college_ids"]["CSE"]),
            roles=("STUDENT",),
            permissions=("reservation:create",),
            token_type="access",
            token_id=uuid.uuid4().hex,
            session_id=uuid.uuid4().hex,
        )
        request = make_request(app)
        plan = ReservationPlanRequest(
            device_id=device_id,
            purpose=f"qa_eval Redis-fallback {index}",
            start_date=day,
            end_date=day,
        )
        async with factory() as session:
            try:
                async with reservation_lock(request, device_id, plan.requested_dates()):
                    created = await ReservationService(
                        session,
                        principal,
                        max_days=31,
                        advance_days=30,
                    ).create(plan, idempotency_key=f"redis-fallback-{manifest['run_id']}-{index}")
                return {"status": 201, "reservation_id": created.created[0].id}
            except ApiError as exc:
                if exc.status_code != 409 or exc.code != "RESERVATION_CONFLICT":
                    raise
                return {"status": exc.status_code, "code": exc.code}

    try:
        submissions = await asyncio.gather(submit(0), submit(1))
        async with factory() as session:
            count = int(
                await session.scalar(
                    select(func.count(models.ReservationItem.id)).where(
                        models.ReservationItem.device_id == device_id,
                        models.ReservationItem.reservation_date == day,
                    )
                )
                or 0
            )
        if sum(result["status"] == 201 for result in submissions) != 1:
            raise AssertionError(f"Redis-down DB race did not elect one winner: {submissions}")
        if count != 1:
            raise AssertionError(f"fresh MySQL read expected one occupied date, got {count}")
        fallback_count = app.state.metrics.counts.get(("reservation_lock_total", "fallback"), 0)
        if fallback_count != 2:
            raise AssertionError(
                f"both requests should observe lock fallback, got {fallback_count}"
            )

        auth_request = make_request(app, "/api/v2/auth/me")
        access = create_access_token(auth_request, session_id="q" * 43)
        try:
            await resolve_principal(auth_request, access, None)  # Redis fails before DB access.
        except ApiError as exc:
            auth_result = {"status": exc.status_code, "code": exc.code}
        else:
            raise AssertionError("authentication unexpectedly succeeded without the session store")
        if auth_result != {"status": 503, "code": "AUTH_SESSION_UNAVAILABLE"}:
            raise AssertionError(f"Redis-down authentication must fail closed, got {auth_result}")

        return {
            "lock_fallback": {
                "redis": "unavailable (isolated localhost port)",
                "results": submissions,
                "fresh_mysql_occupied_days": count,
                "fallback_metric_count": fallback_count,
            },
            "authentication": auth_result,
        }
    finally:
        await dispose_app_redis(app)
        await engine.dispose()


def main() -> None:
    result = asyncio.run(run())
    output = RESULTS / "redis-fallback.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
