"""Seed isolated 1k/10k/100k reservation cohorts and compare deep-page plans.

The direct SQL comparison uses two implementations against the same MySQL rows:
full reservation rows are selected before OFFSET (baseline), versus an indexed
ID-only page followed by a primary-key join (delayed association). The probe
also measures the actual authenticated `/reservations/mine` API. All generated
rows carry a unique purpose prefix and can be removed by this script or the
fixture cleanup command.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "qa_eval"))

from app.infrastructure.db import models  # noqa: E402
from config import BASE_URL, FIXTURE_FILE, RESULTS, require_mysql_dsn  # noqa: E402

SIZES = (1_000, 10_000, 100_000)
BATCH = 1_000
PAGE_SIZE = 20


def _manifest() -> dict[str, Any]:
    path = FIXTURE_FILE if FIXTURE_FILE.is_absolute() else ROOT / FIXTURE_FILE
    return json.loads(path.read_text(encoding="utf-8"))


async def _insert_cohort(
    factory,
    *,
    marker: str,
    user: dict[str, Any],
    college_id: int,
    device_ids: list[int],
    count: int,
) -> None:
    start_year = {1_000: 2000, 10_000: 2050, 100_000: 2100}[count]
    start = date(start_year, 1, 1)
    async with factory() as session:
        for low in range(0, count, BATCH):
            high = min(count, low + BATCH)
            reservations = []
            items = []
            for offset in range(low, high):
                day = start + timedelta(days=offset)
                device_id = device_ids[offset % len(device_ids)]
                reservations.append(
                    {
                        "college_id": college_id,
                        "user_id": int(user["user_id"]),
                        "device_id": device_id,
                        "purpose": f"{marker}:{offset:06d}",
                        "purpose_category": "OTHER",
                        "project_reference": marker,
                        "start_date": day,
                        "end_date": day,
                        "slot_count": 1,
                        "status": "COMPLETED",
                        "handover_status": "RETURNED",
                    }
                )
            await session.execute(models.Reservation.__table__.insert(), reservations)
            reservation_rows = (
                await session.execute(
                    select(
                        models.Reservation.id,
                        models.Reservation.start_date,
                        models.Reservation.device_id,
                    )
                    .where(models.Reservation.project_reference == marker)
                    .order_by(models.Reservation.id.desc())
                    .limit(len(reservations))
                )
            ).all()
            items.extend(
                {
                    "reservation_id": int(row.id),
                    "device_id": int(row.device_id),
                    "date": row.start_date,
                    "slot_index": 0,
                }
                for row in reservation_rows
            )
            await session.execute(models.ReservationItem.__table__.insert(), items)
            await session.commit()
            if high % 10_000 == 0 or high == count:
                print(f"seeded {high:,}/{count:,} rows for cohort {count:,}", flush=True)


async def _cleanup(factory, marker: str) -> int:
    async with factory() as session:
        result = await session.execute(
            delete(models.Reservation).where(
                models.Reservation.project_reference.in_([f"{marker}_{size}" for size in SIZES])
            )
        )
        await session.commit()
        return int(result.rowcount or 0)


async def _cleanup_orphans(factory, manifest: dict[str, Any]) -> int:
    """Remove only benchmark-tagged rows owned by the fixture performance users."""
    user_ids = [int(user["user_id"]) for user in manifest["accounts"]["perf"]]
    async with factory() as session:
        result = await session.execute(
            delete(models.Reservation).where(
                models.Reservation.user_id.in_(user_ids),
                models.Reservation.purpose.startswith("qa_eval_paging_", autoescape=True),
            )
        )
        await session.commit()
        return int(result.rowcount or 0)


async def _time_query(
    factory, statement_builder, *, user_id: int, page: int, repetitions: int
) -> list[float]:
    samples: list[float] = []
    for _ in range(repetitions):
        async with factory() as session:
            started = time.perf_counter()
            rows = (await session.scalars(statement_builder(user_id, page))).all()
            samples.append((time.perf_counter() - started) * 1000)
            if len(rows) != PAGE_SIZE:
                raise AssertionError(f"expected {PAGE_SIZE} rows at page {page}, got {len(rows)}")
    return samples


def _legacy_statement(user_id: int, page: int):
    return (
        select(models.Reservation)
        .where(models.Reservation.user_id == user_id)
        .order_by(models.Reservation.id.desc())
        .offset((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
    )


def _delayed_statement(user_id: int, page: int):
    ids = (
        select(models.Reservation.id.label("id"))
        .where(models.Reservation.user_id == user_id)
        .order_by(models.Reservation.id.desc())
        .offset((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
        .subquery("qa_page_ids")
    )
    return (
        select(models.Reservation)
        .join(ids, ids.c.id == models.Reservation.id)
        .order_by(models.Reservation.id.desc())
    )


async def _login_and_measure(
    user: dict[str, Any], password: str, size: int, pages: list[int], repetitions: int
) -> dict[str, Any]:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        csrf_response = await client.get("/api/v2/auth/csrf")
        csrf_response.raise_for_status()
        csrf = csrf_response.json()["data"]["csrf_token"]
        login = await client.post(
            "/api/v2/auth/login",
            json={"username": user["username"], "password": password},
            headers={"Origin": "http://127.0.0.1:5173", "X-CSRF-Token": csrf},
        )
        login.raise_for_status()
        result: dict[str, Any] = {"size": size, "api": []}
        for page in pages:
            samples = []
            for _ in range(repetitions):
                started = time.perf_counter()
                response = await client.get(
                    "/api/v2/reservations/mine",
                    params={"page": page, "page_size": PAGE_SIZE},
                )
                elapsed = (time.perf_counter() - started) * 1000
                response.raise_for_status()
                payload = response.json()["data"]
                if payload["total"] != size or len(payload["items"]) != PAGE_SIZE:
                    raise AssertionError(
                        f"API cohort mismatch for {size=} {page=}: total={payload['total']} "
                        f"items={len(payload['items'])}"
                    )
                samples.append(elapsed)
            result["api"].append(
                {"page": page, "samples_ms": samples, "median_ms": statistics.median(samples)}
            )
        await client.post(
            "/api/v2/auth/logout",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "X-CSRF-Token": login.json()["data"]["csrf_token"],
            },
        )
        return result


async def run(
    repetitions: int, cleanup_prefix: str | None, cleanup_orphans: bool
) -> dict[str, Any]:
    manifest = _manifest()
    engine = create_async_engine(
        require_mysql_dsn(), pool_pre_ping=True, pool_size=5, max_overflow=5
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    run_id = uuid.uuid4().hex[:10]
    try:
        if cleanup_prefix:
            return {"removed_rows": await _cleanup(factory, cleanup_prefix)}
        if cleanup_orphans:
            return {"removed_rows": await _cleanup_orphans(factory, manifest)}

        prefix = f"qa_eval_paging_{manifest['run_id']}_{run_id}"

        result: dict[str, Any] = {
            "run_id": run_id,
            "dataset_prefix": prefix,
            "page_size": PAGE_SIZE,
            "repetitions": repetitions,
            "cohorts": [],
        }
        perf_users = manifest["accounts"]["perf"]
        college_id = int(manifest["college_ids"]["CSE"])
        device_ids = [int(item) for item in manifest["device_ids"]["CSE"]]

        for index, size in enumerate(SIZES):
            user = perf_users[index]
            marker = f"{prefix}_{size}"
            await _insert_cohort(
                factory,
                marker=marker,
                user=user,
                college_id=college_id,
                device_ids=device_ids,
                count=size,
            )
            pages = [1, max(1, (size - PAGE_SIZE) // PAGE_SIZE + 1)]
            cohort: dict[str, Any] = {"size": size, "pages": pages, "direct_sql": []}
            user_id = int(user["user_id"])
            for page in pages:
                for name, builder in (
                    ("full_row_offset", _legacy_statement),
                    ("id_page_then_join", _delayed_statement),
                ):
                    samples = await _time_query(
                        factory, builder, user_id=user_id, page=page, repetitions=repetitions
                    )
                    cohort["direct_sql"].append(
                        {
                            "strategy": name,
                            "page": page,
                            "samples_ms": samples,
                            "median_ms": statistics.median(samples),
                        }
                    )
            cohort["api"] = await _login_and_measure(
                user, manifest["password"], size, pages, repetitions
            )
            result["cohorts"].append(cohort)

        output = RESULTS / f"pagination-{run_id}.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return {**result, "output": str(output)}
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--cleanup-prefix", help="remove rows created by a reported dataset_prefix")
    parser.add_argument(
        "--cleanup-orphans",
        action="store_true",
        help="remove pagination-probe rows for this fixture's perf accounts",
    )
    args = parser.parse_args()
    if args.repetitions < 3 and not (args.cleanup_prefix or args.cleanup_orphans):
        raise SystemExit("performance comparison requires at least 3 repetitions")
    print(
        json.dumps(
            asyncio.run(run(args.repetitions, args.cleanup_prefix, args.cleanup_orphans)),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
