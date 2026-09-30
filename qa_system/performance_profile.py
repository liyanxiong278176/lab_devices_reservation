"""Repeatable authenticated mixed-read API concurrency profile for the isolated QA runtime."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import math
import time
from collections import Counter
from pathlib import Path

import httpx
from redis import Redis

ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "qa_system"
API_ROOT = "http://127.0.0.1:8000/api/v2"
PROFILES = (5, 10, 25, 50, 100)
REPETITIONS = 3
REQUESTS_PER_USER = 2
ENDPOINTS = (
    "/devices?page=1&page_size=24",
    "/reservations/mine?page=1&page_size=20",
    "/notifications/mine?page=1&size=20",
    "/ai/status",
    "/ai/conversations?limit=50",
)


def nearest_rank(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def reset_only_qa_login_buckets(state: dict[str, object], accounts: dict[str, object]) -> None:
    keys = ["lab:v2:rate:policy-v2:login_ip:ip:127.0.0.1:login"]
    for account in accounts.values():
        username_hash = hashlib.sha256(account["username"].strip().lower().encode()).hexdigest()[
            :24
        ]
        keys.append(f"lab:v2:rate:policy-v2:login:username:{username_hash}:login")
    fixture_ids = json.loads((QA / "results" / "seed_ids.json").read_text(encoding="utf-8"))
    keys.append("lab:v2:rate:policy-v2:default:ip:127.0.0.1:default")
    user_ids = fixture_ids["user"]
    college_ids = fixture_ids["college"]
    keys.extend(
        f"lab:v2:rate:policy-v2:default:user:{int(user_id)}:default" for user_id in user_ids
    )
    keys.extend(
        f"lab:v2:rate:policy-v2:default:college:{int(college_id)}:default"
        for college_id in college_ids
    )
    client = Redis.from_url(str(state["redis_url"]), socket_timeout=2)
    try:
        client.delete(*keys)
    finally:
        client.close()


async def main() -> None:
    state = json.loads((QA / ".runtime-secrets.json").read_text(encoding="utf-8"))
    accounts = json.loads((QA / "results" / "accounts.local.json").read_text(encoding="utf-8"))
    reset_only_qa_login_buckets(state, accounts)
    timeout = httpx.Timeout(30.0, connect=10.0)
    limits = httpx.Limits(max_connections=1000, max_keepalive_connections=1000)
    rows: list[dict[str, object]] = []
    async with httpx.AsyncClient(base_url=API_ROOT, timeout=timeout, limits=limits) as client:
        csrf_response = await client.get("/auth/csrf")
        csrf_response.raise_for_status()
        login = await client.post(
            "/auth/login",
            json=accounts["student_a"],
            headers={
                "Origin": "http://127.0.0.1:5173",
                "X-CSRF-Token": csrf_response.json()["data"]["csrf_token"],
            },
        )
        login.raise_for_status()
        csrf = await client.get("/auth/csrf")
        csrf.raise_for_status()
        client.headers.update(
            {
                "Origin": "http://127.0.0.1:5173",
                "X-CSRF-Token": csrf.json()["data"]["csrf_token"],
            }
        )

        for concurrency in PROFILES:
            for repetition in range(1, REPETITIONS + 1):
                request_count = max(100, concurrency * REQUESTS_PER_USER)
                semaphore = asyncio.Semaphore(concurrency)
                latencies: list[float] = []
                statuses: list[int] = []
                exceptions: list[str] = []

                async def request(index: int) -> None:
                    endpoint = ENDPOINTS[index % len(ENDPOINTS)]
                    async with semaphore:
                        started = time.perf_counter()
                        try:
                            response = await client.get(endpoint)
                            latencies.append((time.perf_counter() - started) * 1000)
                            statuses.append(response.status_code)
                        except Exception as exc:  # report only safe exception class names
                            exceptions.append(type(exc).__name__)

                started = time.perf_counter()
                await asyncio.gather(*(request(index) for index in range(request_count)))
                elapsed = time.perf_counter() - started
                successful = sum(200 <= status < 300 for status in statuses)
                rows.append(
                    {
                        "concurrency": concurrency,
                        "repetition": repetition,
                        "requests": request_count,
                        "successful": successful,
                        "failed": request_count - successful,
                        "exceptions": len(exceptions),
                        "status_counts": dict(sorted(Counter(statuses).items())),
                        "duration_seconds": round(elapsed, 3),
                        "throughput_rps": round(request_count / elapsed, 2),
                        "p50_ms": round(nearest_rank(latencies, 0.50), 2) if latencies else None,
                        "p95_ms": round(nearest_rank(latencies, 0.95), 2) if latencies else None,
                        "max_ms": round(max(latencies), 2) if latencies else None,
                    }
                )
                print(
                    f"concurrency={concurrency} repetition={repetition} requests={request_count} "
                    f"ok={successful} failed={request_count - successful} "
                    f"p95_ms={rows[-1]['p95_ms']} throughput_rps={rows[-1]['throughput_rps']}"
                )

    result_dir = QA / "results"
    result_dir.mkdir(parents=True, exist_ok=True)
    (result_dir / "performance-matrix.json").write_text(
        json.dumps(rows, indent=2), encoding="utf-8"
    )
    with (result_dir / "performance-matrix.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    report = [
        "# Mixed API concurrency profile",
        "",
        "Local disposable QA MySQL/Redis, one authenticated student session, fixture scale only;",
        "read-only mixed device, reservation, notification, and AI status/conversation endpoints.",
        "Rate limiting stays enabled here; all requests share one principal "
        "to expose burst guard behavior.",
        "Each concurrency level was repeated three times; this is not a production capacity claim.",
        "",
        "| Concurrency | Requests | Pass | Fail | HTTP codes | p50 ms | p95 ms | Max ms | RPS |",
        "|---:|---:|---:|---:|:---|---:|---:|---:|---:|",
    ]
    for row in rows:
        report.append(
            (
                "| {concurrency} | {requests} | {successful} | {failed} | "
                "{status_counts} | {p50_ms} | {p95_ms} | {max_ms} | {throughput_rps} |"
            ).format(**row)
        )
    performance_report_path = result_dir / "performance-matrix.md"
    performance_report_path.write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )
    failed = sum(int(row["failed"]) for row in rows)
    print(
        "PERFORMANCE_PROFILE_COMPLETE "
        f"profiles={len(PROFILES)} repetitions={REPETITIONS} failed={failed}"
    )


if __name__ == "__main__":
    asyncio.run(main())
