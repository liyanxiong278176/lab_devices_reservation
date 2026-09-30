"""Exercise reservation contention through a live Uvicorn HTTP endpoint.

This intentionally keeps the normal cookie session, CSRF, rate limiter,
admission middleware, Redis lock, and MySQL unique-index path in the test.
Credentials are read only from environment variables and are never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import httpx
from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.settings import Settings
from app.infrastructure.db.models import ReservationItem
from app.infrastructure.db.session import build_engine, build_session_factory


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * quantile)))
    return ordered[index]


async def run(args: argparse.Namespace) -> int:
    username = os.environ.get("LAB_ACCEPTANCE_USERNAME", "")
    password = os.environ.get("LAB_ACCEPTANCE_PASSWORD", "")
    if not username or not password:
        raise SystemExit("LAB_ACCEPTANCE_USERNAME and LAB_ACCEPTANCE_PASSWORD are required")

    origin = os.environ.get("LAB_ACCEPTANCE_ORIGIN", "http://127.0.0.1:15173")
    target_date = args.date or (date.today() + timedelta(days=10))
    payload = {
        "device_id": args.device_id,
        "start_date": target_date.isoformat(),
        "end_date": target_date.isoformat(),
        "purpose": "隔离环境真实 HTTP 并发验收",
    }
    limits = httpx.Limits(
        max_connections=args.requests,
        max_keepalive_connections=args.requests,
    )
    timeout = httpx.Timeout(connect=15.0, read=45.0, write=15.0, pool=45.0)
    latencies: list[float] = []
    statuses: Counter[int | str] = Counter()
    error_codes: Counter[str] = Counter()

    async with httpx.AsyncClient(
        base_url=args.base_url.rstrip("/"),
        timeout=timeout,
        limits=limits,
        trust_env=False,
    ) as client:
        csrf_response = await client.get("/api/v2/auth/csrf")
        if csrf_response.status_code != 200:
            raise RuntimeError(f"CSRF bootstrap failed: HTTP {csrf_response.status_code}")
        csrf_token = csrf_response.json()["data"]["csrf_token"]
        login_response = await client.post(
            "/api/v2/auth/login",
            json={"username": username, "password": password},
            headers={"Origin": origin, "X-CSRF-Token": csrf_token},
        )
        if login_response.status_code != 200:
            raise RuntimeError(f"isolated test login failed: HTTP {login_response.status_code}")
        csrf_token = login_response.json()["data"]["csrf_token"]
        headers = {"Origin": origin, "X-CSRF-Token": csrf_token}

        gate = asyncio.Semaphore(args.concurrency)
        started = time.perf_counter()

        async def submit(index: int) -> None:
            async with gate:
                request_started = time.perf_counter()
                try:
                    response = await client.post(
                        "/api/v2/reservations",
                        json=payload,
                        headers={
                            **headers,
                            "Idempotency-Key": f"http-race-{args.run_id}-{index}",
                        },
                    )
                    statuses[response.status_code] += 1
                    try:
                        body = response.json()
                    except (json.JSONDecodeError, ValueError):
                        body = {}
                    if isinstance(body, dict) and body.get("code"):
                        error_codes[str(body["code"])] += 1
                except httpx.HTTPError as exc:
                    statuses["transport_error"] += 1
                    error_codes[type(exc).__name__] += 1
                finally:
                    latencies.append(time.perf_counter() - request_started)

        await asyncio.gather(*(submit(index) for index in range(args.requests)))
        elapsed = time.perf_counter() - started

        metrics_token = os.environ.get("LAB_METRICS_TOKEN")
        metric_lines: list[str] = []
        if metrics_token:
            metrics_response = await client.get(
                "/api/v2/metrics",
                headers={"Authorization": f"Bearer {metrics_token}"},
            )
            if metrics_response.status_code == 200:
                metric_lines = [
                    line
                    for line in metrics_response.text.splitlines()
                    if (
                        line.startswith("http_requests_total{")
                        and (
                            'route="/reservations"' in line
                            or (
                                'route="__unmatched__"' in line
                                and 'status="503"' in line
                            )
                        )
                    )
                    or (
                        line.startswith(
                            (
                                "http_request_duration_seconds_bucket{",
                                "http_request_duration_seconds_sum{",
                                "http_request_duration_seconds_count{",
                            )
                        )
                        and 'route="/reservations"' in line
                    )
                    or line.startswith("reservation_lock_total{")
                    or line.startswith("lab_db_pool_")
                ]

    settings = Settings()
    engine = build_engine(settings)
    factory = build_session_factory(engine)
    try:
        async with factory() as session:
            occupied_days = int(
                await session.scalar(
                    select(func.count(ReservationItem.id)).where(
                        ReservationItem.device_id == args.device_id,
                        ReservationItem.reservation_date == target_date,
                    )
                )
                or 0
            )
    finally:
        await engine.dispose()

    result = {
        "requests": args.requests,
        "concurrency": args.concurrency,
        "target_date": target_date.isoformat(),
        "elapsed_seconds": round(elapsed, 3),
        "throughput_rps": round(args.requests / elapsed, 2) if elapsed else 0.0,
        "latency_ms": {
            "p50": round(percentile(latencies, 0.50) * 1000, 2),
            "p95": round(percentile(latencies, 0.95) * 1000, 2),
            "p99": round(percentile(latencies, 0.99) * 1000, 2),
            "max": round(max(latencies, default=0.0) * 1000, 2),
            "mean": round(statistics.fmean(latencies) * 1000, 2) if latencies else 0.0,
        },
        "http_statuses": {str(key): value for key, value in sorted(statuses.items(), key=str)},
        "api_error_codes": dict(error_codes),
        "database_occupied_rows_for_device_day": occupied_days,
        "prometheus_samples": metric_lines,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

    expected_statuses = {201, 409, 429, 503}
    actual_statuses = {status for status in statuses if isinstance(status, int)}
    if (
        statuses[201] != 1
        or statuses[409] < 1
        or statuses["transport_error"]
        or actual_statuses - expected_statuses
        or occupied_days != 1
    ):
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:18000")
    parser.add_argument("--device-id", type=int, required=True)
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=1000)
    parser.add_argument("--run-id", default=str(time.time_ns()))
    args = parser.parse_args()
    if args.requests < 2 or args.concurrency < 1:
        parser.error("--requests must be at least 2 and --concurrency at least 1")
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
