"""Create isolated history and benchmark uniformly distributed reservation pages.

The generated rows belong to a dedicated E2E college. Remove the entire fixture
with ``scripts/e2e_fixture.py cleanup --prefix <prefix>`` after the run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import sys
import time
from collections import Counter
from datetime import date, timedelta
from itertools import count
from math import ceil
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.settings import Settings
from app.infrastructure.db.models import College, Device, Reservation, User
from app.infrastructure.db.session import build_engine, build_session_factory
from sqlalchemy import insert, select

PREFIX_PATTERN = re.compile(r"e2e-perf-[a-z0-9-]{6,24}")
HISTORY_RESERVATIONS = 10_000
PAGE_SIZE = 20
PAGE_COUNT = ceil(HISTORY_RESERVATIONS / PAGE_SIZE)


def validate_prefix(value: str) -> str:
    if not PREFIX_PATTERN.fullmatch(value):
        raise ValueError("prefix must match e2e-perf-[a-z0-9-]{6,24}")
    return value


async def seed_history(prefix: str) -> None:
    prefix = validate_prefix(prefix)
    settings = Settings()
    engine = build_engine(settings)
    factory = build_session_factory(engine)
    try:
        async with factory() as session:
            college = await session.scalar(select(College).where(College.code == prefix.upper()))
            user = await session.scalar(select(User).where(User.username == f"{prefix}-user"))
            devices = list(
                (
                    await session.scalars(
                        select(Device).where(Device.college_id == college.id if college else False)
                    )
                ).all()
            )
            if college is None or user is None or len(devices) != 2:
                raise RuntimeError("expected the untouched two-device E2E fixture")
            existing = int(
                await session.scalar(
                    select(Reservation.id).where(Reservation.college_id == college.id).limit(1)
                )
                is not None
            )
            if existing:
                raise RuntimeError("fixture already contains reservations; use a fresh prefix")

            load_devices = [
                Device(
                    name=f"{prefix}-load-device-{index:03d}",
                    brand="capacity-test",
                    model="capacity-test",
                    status="IDLE",
                    college_id=college.id,
                    lab_id=devices[0].lab_id,
                    need_approval=False,
                    max_reservation_days=31,
                )
                for index in range(98)
            ]
            session.add_all(load_devices)
            await session.flush()
            device_ids = [device.id for device in devices] + [device.id for device in load_devices]
            today = date.today()
            rows = [
                {
                    "college_id": college.id,
                    "user_id": user.id,
                    "device_id": device_ids[index % len(device_ids)],
                    "purpose": f"{prefix}-history-{index:05d}",
                    "purpose_category": "OTHER",
                    "start_date": today - timedelta(days=(index % 3000) + 1),
                    "end_date": today - timedelta(days=(index % 3000) + 1),
                    "slot_count": 1,
                    "status": "COMPLETED",
                }
                for index in range(HISTORY_RESERVATIONS)
            ]
            await session.execute(insert(Reservation), rows)
            await session.commit()
    finally:
        await engine.dispose()
    print(json.dumps({"prefix": prefix, "devices": 100, "reservations": 10_000}))


def percentile(samples: list[float], ratio: float) -> float:
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, max(0, ceil(len(ordered) * ratio) - 1))]


def build_page_schedule(requests: int, *, seed: int) -> list[int]:
    """Return a shuffled schedule whose per-page request counts differ by at most one."""
    base, remainder = divmod(requests, PAGE_COUNT)
    pages = [
        page
        for page in range(1, PAGE_COUNT + 1)
        for _ in range(base + (1 if page <= remainder else 0))
    ]
    random.Random(seed).shuffle(pages)
    return pages


async def authenticate(
    client: httpx.AsyncClient,
    *,
    username: str,
    password: str,
    origin: str,
) -> None:
    csrf_response = await client.get("auth/csrf")
    csrf_response.raise_for_status()
    csrf_token = csrf_response.json()["data"]["csrf_token"]
    login_response = await client.post(
        "auth/login",
        json={"username": username, "password": password},
        headers={"Origin": origin, "X-CSRF-Token": csrf_token},
    )
    login_response.raise_for_status()
    client.headers["Origin"] = origin
    client.headers["X-CSRF-Token"] = login_response.json()["data"]["csrf_token"]


async def smoke_dashboard(args: argparse.Namespace) -> None:
    base_url = f"{args.base_url.rstrip('/')}/"
    async with (
        httpx.AsyncClient(base_url=base_url, timeout=30) as student_client,
        httpx.AsyncClient(base_url=base_url, timeout=30) as admin_client,
    ):
        await authenticate(
            student_client,
            username=args.username,
            password=args.password,
            origin=args.origin,
        )
        await authenticate(
            admin_client,
            username=args.admin_username,
            password=args.password,
            origin=args.origin,
        )
        student_response, overview_response = await asyncio.gather(
            student_client.get("dashboard/me"),
            admin_client.get("dashboard/overview?groupBy=category&days=30"),
        )
    results = {
        "student_dashboard_status": student_response.status_code,
        "admin_overview_status": overview_response.status_code,
    }
    print(json.dumps(results, indent=2))
    if any(status != 200 for status in results.values()):
        raise SystemExit("dashboard MySQL smoke test failed")


async def run_benchmark(args: argparse.Namespace) -> None:
    base_urls = args.base_urls or [args.base_url]
    limits = httpx.Limits(
        max_connections=max(ceil(args.concurrency / len(base_urls)), 20),
        max_keepalive_connections=max(ceil(args.concurrency / len(base_urls)), 20),
    )
    timeout = httpx.Timeout(args.timeout_seconds)
    samples: list[float] = []
    statuses: Counter[str] = Counter()
    failures: Counter[str] = Counter()
    clients = [
        httpx.AsyncClient(
            base_url=f"{base_url.rstrip('/')}/",
            timeout=timeout,
            limits=limits,
        )
        for base_url in base_urls
    ]

    async def login_client(client: httpx.AsyncClient) -> None:
        await authenticate(
            client,
            username=args.username,
            password=args.password,
            origin=args.origin,
        )
        me_response = await client.get("auth/me")
        me_response.raise_for_status()

    try:
        await asyncio.gather(*(login_client(client) for client in clients))

        async def one(index: int, page: int) -> None:
            path = f"reservations/mine?page={page}&page_size={PAGE_SIZE}"
            client = clients[index % len(clients)]
            started = time.perf_counter()
            try:
                response = await client.get(path)
                samples.append((time.perf_counter() - started) * 1000)
                statuses[str(response.status_code)] += 1
                if response.status_code != 200:
                    try:
                        body = response.json()
                        failures[str(body.get("code", response.status_code))] += 1
                    except ValueError:
                        failures[str(response.status_code)] += 1
            except httpx.HTTPError as exc:
                failures[type(exc).__name__] += 1

        if args.warmup:
            warmup_pages = build_page_schedule(args.warmup, seed=args.page_seed + 1)
            await asyncio.gather(
                *(one(index, page) for index, page in enumerate(warmup_pages))
            )
            samples.clear()
            statuses.clear()
            failures.clear()

        request_pages = build_page_schedule(args.requests, seed=args.page_seed)
        page_request_counts = Counter(request_pages)
        started = time.perf_counter()
        if args.burst:
            await asyncio.gather(
                *(one(index, page) for index, page in enumerate(request_pages))
            )
        else:
            indexes = count()

            async def worker() -> None:
                while (index := next(indexes)) < args.requests:
                    await one(index, request_pages[index])

            await asyncio.gather(*(worker() for _ in range(args.concurrency)))
        elapsed = time.perf_counter() - started
    finally:
        await asyncio.gather(*(client.aclose() for client in clients))

    summary = {
        "requests": args.requests,
        "workload": "authenticated /reservations/mine reads with uniform page distribution",
        "page_size": PAGE_SIZE,
        "total_pages": PAGE_COUNT,
        "covered_pages": len(page_request_counts),
        "min_requests_per_page": min(page_request_counts.values()),
        "max_requests_per_page": max(page_request_counts.values()),
        "concurrency": args.requests if args.burst else args.concurrency,
        "burst": args.burst,
        "elapsed_seconds": round(elapsed, 3),
        "throughput_requests_per_second": round(args.requests / elapsed, 2),
        "status_counts": dict(statuses),
        "transport_failures": dict(failures),
        "latency_ms": {
            "p50": round(percentile(samples, 0.50), 2) if samples else None,
            "p95": round(percentile(samples, 0.95), 2) if samples else None,
            "p99": round(percentile(samples, 0.99), 2) if samples else None,
            "max": round(max(samples), 2) if samples else None,
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if sum(statuses.values()) != args.requests or failures or statuses != {"200": args.requests}:
        raise SystemExit("capacity run had non-200 responses or transport failures")
    if args.target_p95_ms is not None and percentile(samples, 0.95) > args.target_p95_ms:
        raise SystemExit(f"p95 target failed: {summary['latency_ms']['p95']} ms")


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    seed_parser = subparsers.add_parser("seed-history")
    seed_parser.add_argument("--prefix", required=True)
    smoke_parser = subparsers.add_parser("dashboard-smoke")
    smoke_parser.add_argument("--base-url", default="http://127.0.0.1:8000/api/v2")
    smoke_parser.add_argument("--origin", default="http://127.0.0.1:5173")
    smoke_parser.add_argument("--username", required=True)
    smoke_parser.add_argument("--admin-username", required=True)
    smoke_parser.add_argument("--password", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--base-url", default="http://127.0.0.1:8000/api/v2")
    run_parser.add_argument("--base-urls", nargs="+")
    run_parser.add_argument("--origin", default="http://127.0.0.1:5173")
    run_parser.add_argument("--username", required=True)
    run_parser.add_argument("--password", required=True)
    run_parser.add_argument("--requests", type=int, default=1_000)
    run_parser.add_argument("--concurrency", type=int, default=20)
    run_parser.add_argument("--burst", action="store_true")
    run_parser.add_argument("--warmup", type=int, default=20)
    run_parser.add_argument("--page-seed", type=int, default=20261003)
    run_parser.add_argument("--timeout-seconds", type=float, default=60)
    run_parser.add_argument("--target-p95-ms", type=float)
    args = parser.parse_args()
    if args.command == "seed-history":
        asyncio.run(seed_history(args.prefix))
    elif args.command == "dashboard-smoke":
        asyncio.run(smoke_dashboard(args))
    else:
        asyncio.run(run_benchmark(args))


if __name__ == "__main__":
    main()
