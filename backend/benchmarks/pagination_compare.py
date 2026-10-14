"""HTTP A/B benchmark; traditional pagination exists only in this isolated harness.

The production /reservations/mine route, auth, count, ORM eager loads and response
serializer are identical. The baseline applies SQL OFFSET/LIMIT to full rows;
the treatment runs the unchanged production ID-subquery/deferred-join method.
Never import the baseline into the production application.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from collections import Counter
from itertools import count
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import uvicorn
from app.api.v2.schemas import ReservationPage
from app.application.reservations import ReservationService, _reservation_data
from app.core.errors import ApiError
from app.core.settings import Settings
from app.infrastructure.db.models import Reservation
from app.infrastructure.db.pagination import page_metadata, page_offset
from benchmarks.http_read_capacity import (
    PAGE_COUNT,
    PAGE_SIZE,
    authenticate,
    build_page_schedule,
    percentile,
)
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload


async def traditional_list_mine(
    self: ReservationService,
    *,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    handover_status: str | None = None,
) -> ReservationPage:
    """Baseline SQL only: scope/filter full rows before bounded OFFSET/LIMIT."""
    if not self.principal.has_permission("reservation:read:own"):
        raise ApiError("FORBIDDEN", "当前账号没有查看个人预约的权限", 403)
    offset = page_offset(page, page_size)
    conditions = [Reservation.user_id == self.principal.user_id]
    scope = self._college_id()
    if scope is not None:
        conditions.append(Reservation.college_id == scope)
    if status:
        conditions.append(Reservation.status == status)
    if handover_status:
        conditions.append(Reservation.handover_status == handover_status)
    total = int(
        await self.session.scalar(select(func.count(Reservation.id)).where(*conditions)) or 0
    )
    stmt = (
        select(Reservation)
        .where(*conditions)
        .options(
            selectinload(Reservation.device),
            selectinload(Reservation.days),
            selectinload(Reservation.inspections),
            selectinload(Reservation.handover),
            selectinload(Reservation.fault_repair),
        )
        .order_by(Reservation.id.desc())
        .offset(offset)
        .limit(page_size)
    )
    reservations = list((await self.session.scalars(stmt)).all())
    pages, truncated = page_metadata(total, page_size)
    return ReservationPage(
        items=[_reservation_data(item) for item in reservations],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
        truncated=truncated,
    )


def serve(strategy: str, port: int) -> None:
    from app.main import create_app

    settings = Settings(environment="test", enable_workers=False, rate_limit_enabled=False)
    if not settings.mysql_dsn.split("/", 3)[-1].startswith("lab_resume_"):
        raise RuntimeError("A/B server requires an isolated lab_resume_* database")
    if strategy == "traditional":
        ReservationService.list_mine = traditional_list_mine
    uvicorn.run(
        create_app(settings),
        host="127.0.0.1",
        port=port,
        loop="app.core.uvicorn_loop:platform_loop_factory",
        access_log=False,
    )


async def compare(args: argparse.Namespace) -> None:
    # No passwords or session material is included in saved measurements.
    args.output.mkdir(parents=True, exist_ok=True)
    settings = Settings()
    from sqlalchemy.engine import make_url

    if not (make_url(settings.mysql_dsn).database or "").startswith("lab_resume_"):
        raise RuntimeError("A/B client requires an isolated lab_resume_* database")
    clients = {
        strategy: httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}/api/v2/",
            timeout=60,
            limits=httpx.Limits(
                max_connections=args.concurrency,
                max_keepalive_connections=min(20, args.concurrency),
            ),
        )
        for strategy, port in (
            ("traditional", args.traditional_port),
            ("deferred", args.deferred_port),
        )
    }
    origin = "http://127.0.0.1:5175"
    measurements = []
    hashes: dict[tuple[int, str, str], str] = {}
    pooled: dict[str, list[float]] = {strategy: [] for strategy in clients}
    raw_samples = []

    async def read(
        strategy: str, page: int, status: str = "", handover_status: str = ""
    ) -> tuple[float, int, str]:
        started = time.perf_counter()
        response = await clients[strategy].get(
            "reservations/mine",
            params={
                "page": page,
                "page_size": PAGE_SIZE,
                **({"status": status} if status else {}),
                **({"handover_status": handover_status} if handover_status else {}),
            },
        )
        latency = (time.perf_counter() - started) * 1000
        response.raise_for_status()
        data = response.json()["data"]
        if not status and not handover_status:
            assert data["total"] == 10_000 and data["pages"] == PAGE_COUNT
            assert len(data["items"]) == PAGE_SIZE
        digest = hashlib.sha256(
            json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        key = (page, status, handover_status)
        if key in hashes and hashes[key] != digest:
            raise AssertionError(f"A/B response mismatch for page/filter {key}")
        hashes[key] = digest
        return latency, response.status_code, digest

    try:
        for client in clients.values():
            await authenticate(
                client, username=args.username, password=args.password, origin=origin
            )
        # Check filter equivalence as well as the full-page workload below.
        for page, status, handover in (
            (1, "COMPLETED", ""),
            (1, "PENDING", ""),
            (1, "", "RETURNED"),
        ):
            for strategy in clients:
                await read(strategy, page, status, handover)
        for round_index in range(args.rounds):
            schedule = build_page_schedule(args.requests, seed=args.seed + round_index)
            order = (
                ("traditional", "deferred") if round_index % 2 == 0 else ("deferred", "traditional")
            )
            for strategy in order:
                # Equal warmed buffer-pool conditions; warm every reachable page.
                warmup_schedule = build_page_schedule(PAGE_COUNT, seed=args.seed - 1)
                warmup_indexes = count()

                async def warmup_worker() -> None:
                    while (index := next(warmup_indexes)) < len(warmup_schedule):
                        await read(strategy, warmup_schedule[index])

                await asyncio.gather(*(warmup_worker() for _ in range(args.concurrency)))
                indexes = count()
                latencies = []
                statuses: Counter[int] = Counter()

                async def worker() -> None:
                    while (index := next(indexes)) < args.requests:
                        page = schedule[index]
                        started_ns = time.perf_counter_ns()
                        latency, status_code, digest = await read(strategy, page)
                        completed_ns = time.perf_counter_ns()
                        latencies.append(latency)
                        statuses[status_code] += 1
                        raw_samples.append(
                            {
                                "round": round_index + 1,
                                "strategy": strategy,
                                "request_index": index,
                                "page": page,
                                "latency_ms": round(latency, 4),
                                "status": status_code,
                                "data_sha256": digest,
                                "started_ns": started_ns,
                                "completed_ns": completed_ns,
                            }
                        )

                started = time.perf_counter()
                await asyncio.gather(*(worker() for _ in range(args.concurrency)))
                elapsed = time.perf_counter() - started
                pooled[strategy].extend(latencies)
                result = {
                    "round": round_index + 1,
                    "strategy": strategy,
                    "requests": len(latencies),
                    "concurrency": args.concurrency,
                    "status_counts": dict(statuses),
                    "elapsed_seconds": round(elapsed, 4),
                    "throughput_rps": round(args.requests / elapsed, 2),
                    "p50_ms": round(percentile(latencies, 0.5), 2),
                    "p95_ms": round(percentile(latencies, 0.95), 2),
                    "p99_ms": round(percentile(latencies, 0.99), 2),
                }
                measurements.append(result)
                with (args.output / "pagination-rounds.jsonl").open(
                    "a", encoding="utf-8"
                ) as progress:
                    progress.write(json.dumps(result) + "\n")
                print(json.dumps(result), flush=True)
    finally:
        await asyncio.gather(*(client.aclose() for client in clients.values()))

    summary = {}
    for strategy, latencies in pooled.items():
        elapsed = sum(
            item["elapsed_seconds"] for item in measurements if item["strategy"] == strategy
        )
        summary[strategy] = {
            "requests": len(latencies),
            "p95_ms": round(percentile(latencies, 0.95), 2),
            "p99_ms": round(percentile(latencies, 0.99), 2),
            "throughput_rps": round(len(latencies) / elapsed, 2),
        }
    before, after = summary["traditional"]["p95_ms"], summary["deferred"]["p95_ms"]
    report = {
        "workload": "full authenticated HTTP /api/v2/reservations/mine",
        "rows": 10_000,
        "devices": 100,
        "page_size": PAGE_SIZE,
        "covered_pages": PAGE_COUNT,
        "concurrency": args.concurrency,
        "requests_per_strategy_per_round": args.requests,
        "rounds": args.rounds,
        "warmup_requests_per_strategy_per_round": PAGE_COUNT,
        "order": [
            ["traditional", "deferred"] if index % 2 == 0 else ["deferred", "traditional"]
            for index in range(args.rounds)
        ],
        "matching_response_pages": len([key for key in hashes if key[1:] == ("", "")]),
        "rate_limit_enabled": False,
        "workers_enabled": False,
        "database_indexes": "identical for both strategies; no index changes",
        "measurements": measurements,
        "pooled": summary,
        "p95_reduction_ms": round(before - after, 2),
        "p95_reduction_percent": round((before - after) / before * 100, 2),
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "pagination-comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.output / "pagination-samples.jsonl").write_text(
        "\n".join(json.dumps(sample) for sample in raw_samples) + "\n", encoding="utf-8"
    )
    print(json.dumps({"pooled": summary, "p95_reduction_ms": before - after}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    server = subparsers.add_parser("serve")
    server.add_argument("--strategy", choices=("traditional", "deferred"), required=True)
    server.add_argument("--port", type=int, required=True)
    run = subparsers.add_parser("compare")
    run.add_argument("--traditional-port", type=int, default=8006)
    run.add_argument("--deferred-port", type=int, default=8007)
    run.add_argument("--username", required=True)
    run.add_argument("--password", required=True)
    run.add_argument("--requests", type=int, default=1000)
    run.add_argument("--concurrency", type=int, default=1)
    run.add_argument("--rounds", type=int, default=3)
    run.add_argument("--seed", type=int, default=20261011)
    run.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "serve":
        serve(args.strategy, args.port)
    else:
        asyncio.run(compare(args))


if __name__ == "__main__":
    main()
