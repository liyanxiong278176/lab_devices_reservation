"""Seed 1k/10k/100k disposable device cohorts and measure delayed-pagination reads."""

from __future__ import annotations

import asyncio
import csv
import json
import math
import sys
import time
from pathlib import Path

import httpx
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "qa_system"
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
API_ROOT = "http://127.0.0.1:8000/api/v2"
TARGETS = (1_000, 10_000, 100_000)
BATCH_SIZE = 1_000


def percentile(values: list[float], value: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(value * len(ordered)) - 1)
    return ordered[index]


async def insert_cohort(
    engine, device_model, college_id: int, lab_id: int, run_suffix: str, size: int
) -> float:
    started = time.perf_counter()
    marker = f"QA_SCALE_{size}"
    statement = insert(device_model)
    async with engine.begin() as connection:
        for batch_start in range(0, size, BATCH_SIZE):
            batch_end = min(size, batch_start + BATCH_SIZE)
            rows = [
                {
                    "college_id": college_id,
                    "lab_id": lab_id,
                    "category_id": None,
                    "name": f"{marker}_{index:06d}",
                    "brand": "QAEVAL",
                    "model": "SCALE",
                    "specs": None,
                    "image_url": None,
                    "status": "IDLE",
                    "need_approval": False,
                    "max_reservation_days": 8,
                    "description": None,
                    "tags": ["qaeval", "scale"],
                    "accessory_checklist": [],
                    "asset_code": f"QAEVAL_{run_suffix}_S{size}_{index:06d}",
                    "serial_number": None,
                    "purchase_date": None,
                    "warranty_until": None,
                    "allow_external_loan": False,
                    "risk_level": "STANDARD",
                    "requires_safety_ack": False,
                    "requires_qualification": False,
                    "max_advance_days": None,
                }
                for index in range(batch_start, batch_end)
            ]
            await connection.execute(statement, rows)
    return time.perf_counter() - started


async def main() -> None:
    from app.infrastructure.db.models import Device

    state = json.loads((QA / ".runtime-secrets.json").read_text(encoding="utf-8"))
    seed = json.loads((QA / "results" / "seed_ids.json").read_text(encoding="utf-8"))
    accounts = json.loads((QA / "results" / "accounts.local.json").read_text(encoding="utf-8"))
    suffix = str(state["suffix"])
    college_a_id = int(seed["college"][0])
    lab_a_id = int(seed["lab"][0])
    engine = create_async_engine(str(state["mysql_dsn"]), pool_pre_ping=True)
    timeout = httpx.Timeout(60.0, connect=10.0)
    client = httpx.AsyncClient(base_url=API_ROOT, timeout=timeout)
    measurements: list[dict[str, object]] = []
    insert_rows: list[dict[str, object]] = []
    try:
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

        for size in TARGETS:
            insert_seconds = await insert_cohort(
                engine, Device, college_a_id, lab_a_id, suffix, size
            )
            insert_rows.append({"cohort_rows": size, "insert_seconds": round(insert_seconds, 2)})
            marker = f"QA_SCALE_{size}"
            last_page = math.ceil(size / 24)
            pages = {
                "shallow": (1, 2, 3),
                "deep": tuple(range(max(1, last_page - 3), last_page)),
            }
            for depth, page_numbers in pages.items():
                for repetition, page_number in enumerate(page_numbers, start=1):
                    started = time.perf_counter()
                    response = await client.get(
                        "/devices",
                        params={"search": marker, "page": page_number, "page_size": 24},
                    )
                    elapsed_ms = (time.perf_counter() - started) * 1000
                    if response.status_code != 200:
                        raise RuntimeError(
                            f"device list returned HTTP {response.status_code} at {size} rows"
                        )
                    payload = response.json()["data"]
                    if int(payload["total"]) != size or len(payload["items"]) != 24:
                        raise RuntimeError(
                            f"pagination mismatch at {size} rows, page {page_number}"
                        )
                    measurements.append(
                        {
                            "cohort_rows": size,
                            "depth": depth,
                            "repetition": repetition,
                            "page": page_number,
                            "rows_returned": len(payload["items"]),
                            "latency_ms": round(elapsed_ms, 2),
                            "http_status": response.status_code,
                        }
                    )
            cohort_measurements = [item for item in measurements if item["cohort_rows"] == size]
            shallow_ms = [
                float(item["latency_ms"])
                for item in cohort_measurements
                if item["depth"] == "shallow"
            ]
            deep_ms = [
                float(item["latency_ms"]) for item in cohort_measurements if item["depth"] == "deep"
            ]
            print(
                f"cohort_rows={size} insert_seconds={insert_seconds:.2f} "
                f"shallow_p95_ms={percentile(shallow_ms, 0.95):.2f} "
                f"deep_p95_ms={percentile(deep_ms, 0.95):.2f}",
                flush=True,
            )
    finally:
        await client.aclose()
        await engine.dispose()

    result_dir = QA / "results"
    (result_dir / "database-scale-profile.json").write_text(
        json.dumps({"inserts": insert_rows, "measurements": measurements}, indent=2),
        encoding="utf-8",
    )
    with (result_dir / "database-scale-profile.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(measurements[0]))
        writer.writeheader()
        writer.writerows(measurements)

    report = [
        "# Device-list data-scale profile",
        "",
        "Synthetic cohorts in the disposable QA MySQL schema; each uses its own marker.",
        "Three unique pages per depth; the API cache remains enabled.",
        "",
        "| Cohort rows | Insert s | Shallow p50 ms | Shallow max ms | Deep p50 ms | Deep max ms |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    insert_seconds_by_size = {
        int(row["cohort_rows"]): float(row["insert_seconds"]) for row in insert_rows
    }
    for size in TARGETS:
        insert_seconds = insert_seconds_by_size[size]
        item_rows = [row for row in measurements if row["cohort_rows"] == size]
        shallow = [float(row["latency_ms"]) for row in item_rows if row["depth"] == "shallow"]
        deep = [float(row["latency_ms"]) for row in item_rows if row["depth"] == "deep"]
        report.append(
            f"| {size} | {insert_seconds:.2f} | {percentile(shallow, 0.50):.2f} | "
            f"{max(shallow):.2f} | {percentile(deep, 0.50):.2f} | {max(deep):.2f} |"
        )
    (result_dir / "database-scale-profile.md").write_text(
        "\n".join(report) + "\n", encoding="utf-8"
    )
    print("DATABASE_SCALE_PROFILE_COMPLETE cohorts=1000,10000,100000", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
