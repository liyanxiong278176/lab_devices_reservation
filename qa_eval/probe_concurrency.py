"""Fresh real-MySQL/API race probes for the isolated QA fixture.

No repository test fixtures are imported. Requests go through the live API;
database assertions use a new SQLAlchemy connection after all requests finish.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from httpx import AsyncClient, Limits
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "qa_eval"))

from app.infrastructure.db import models  # noqa: E402
from config import BASE_URL, FIXTURE_FILE, RESULTS, require_mysql_dsn  # noqa: E402


@dataclass
class Persona:
    username: str
    user_id: int
    client: AsyncClient
    csrf: str

    def headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        result = {
            "Origin": "http://127.0.0.1:5173",
            "X-CSRF-Token": self.csrf,
        }
        if extra:
            result.update(extra)
        return result


async def login_personas(manifest: dict[str, Any], count: int) -> list[Persona]:
    accounts = manifest["accounts"]["students"]["CSE"]
    password = manifest["password"]
    personas: list[Persona] = []
    for index in range(count):
        account = accounts[index % len(accounts)]
        client = AsyncClient(
            base_url=BASE_URL,
            timeout=60,
            limits=Limits(max_connections=120, max_keepalive_connections=20),
        )
        csrf_response = await client.get("/api/v2/auth/csrf")
        if csrf_response.status_code != 200:
            raise RuntimeError(f"CSRF bootstrap failed: {csrf_response.status_code}")
        csrf = csrf_response.json()["data"]["csrf_token"]
        logged_in = await client.post(
            "/api/v2/auth/login",
            json={"username": account["username"], "password": password},
            headers={"Origin": "http://127.0.0.1:5173", "X-CSRF-Token": csrf},
        )
        if logged_in.status_code != 200:
            raise RuntimeError(f"QA login failed: HTTP {logged_in.status_code}")
        personas.append(
            Persona(
                username=account["username"],
                user_id=int(account["user_id"]),
                client=client,
                csrf=logged_in.json()["data"]["csrf_token"],
            )
        )
    return personas


async def db_day_counts(factory, device_id: int, dates: list[date]) -> dict[str, int]:
    """Read counts in a new session after all competing HTTP requests complete."""
    async with factory() as session:
        rows = (
            await session.execute(
                select(models.ReservationItem.reservation_date, func.count())
                .where(
                    models.ReservationItem.device_id == device_id,
                    models.ReservationItem.reservation_date.in_(dates),
                )
                .group_by(models.ReservationItem.reservation_date)
            )
        ).all()
    found = {day.isoformat(): int(amount) for day, amount in rows}
    return {day.isoformat(): found.get(day.isoformat(), 0) for day in dates}


async def race_reservations(
    personas: list[Persona],
    *,
    manifest: dict[str, Any],
    device_id: int,
    starts_ends: list[tuple[date, date]],
    case: str,
) -> list[dict[str, Any]]:
    gate = asyncio.Barrier(len(starts_ends))
    run_id = manifest["run_id"]

    async def request_one(index: int, bounds: tuple[date, date]) -> dict[str, Any]:
        start, end = bounds
        persona = personas[index % len(personas)]
        await gate.wait()
        response = await persona.client.post(
            "/api/v2/reservations",
            json={
                "device_id": device_id,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "purpose": f"qa_eval {case} {index}",
            },
            headers=persona.headers(
                {"Idempotency-Key": f"qaeval-{run_id}-{case}-{index}-{uuid.uuid4().hex[:8]}"}
            ),
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        return {
            "status": response.status_code,
            "code": payload.get("code"),
            "message": payload.get("message"),
            "request_id": payload.get("request_id"),
            "user_id": persona.user_id,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "reservation_id": (payload.get("data") or {}).get("created", [{}])[0].get("id")
            if response.status_code == 201
            else None,
        }

    return await asyncio.gather(
        *(request_one(index, bounds) for index, bounds in enumerate(starts_ends))
    )


def assert_race(results: list[dict[str, Any]], expected_successes: int, case: str) -> None:
    success = sum(item["status"] == 201 for item in results)
    conflicts = sum(
        item["status"] == 409 and item["code"] == "RESERVATION_CONFLICT" for item in results
    )
    unexpected = [
        item
        for item in results
        if not (
            item["status"] == 201
            or (item["status"] == 409 and item["code"] == "RESERVATION_CONFLICT")
        )
    ]
    if success != expected_successes or len(unexpected) or success + conflicts != len(results):
        raise AssertionError(
            f"{case}: expected {expected_successes} winner(s), got success={success}, "
            f"409={conflicts}, unexpected={unexpected[:5]}"
        )


async def run(manifest_path: Path, sizes: list[int]) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    engine = create_async_engine(
        require_mysql_dsn(), pool_pre_ping=True, pool_size=12, max_overflow=12
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    personas: list[Persona] = []
    today = date.today()
    device_ids = manifest["device_ids"]["CSE"]
    results: dict[str, Any] = {"run_id": manifest["run_id"], "database": "MySQL", "races": []}
    try:
        async with factory() as session:
            dialect = session.bind.dialect.name if session.bind else "unknown"
            if dialect != "mysql":
                raise RuntimeError(f"Refusing concurrency test on non-MySQL dialect: {dialect}")

        personas = await login_personas(
            manifest, min(20, len(manifest["accounts"]["students"]["CSE"]))
        )
        for size in sizes:
            device_id = device_ids[1]
            day = today + timedelta(days=2 + len(results["races"]) + size % 10)
            race = await race_reservations(
                personas,
                manifest=manifest,
                device_id=device_id,
                starts_ends=[(day, day) for _ in range(size)],
                case=f"same-day-{size}",
            )
            assert_race(race, 1, f"same-day-{size}")
            counts = await db_day_counts(factory, device_id, [day])
            if counts[day.isoformat()] != 1:
                raise AssertionError(f"new MySQL connection saw {counts} after same-day race")
            results["races"].append(
                {
                    "case": f"same-day-{size}",
                    "request_count": size,
                    "success": 1,
                    "conflict_409": size - 1,
                    "db_day_counts": counts,
                }
            )

        overlap_start = today + timedelta(days=18)
        overlap_ranges = [
            (overlap_start, overlap_start + timedelta(days=2)),
            (overlap_start + timedelta(days=2), overlap_start + timedelta(days=4)),
        ]
        overlap = await race_reservations(
            personas,
            manifest=manifest,
            device_id=device_ids[2],
            starts_ends=overlap_ranges,
            case="partial-overlap",
        )
        assert_race(overlap, 1, "partial-overlap")
        overlap_days = [overlap_start + timedelta(days=n) for n in range(5)]
        overlap_counts = await db_day_counts(factory, device_ids[2], overlap_days)
        if sum(overlap_counts.values()) != 3 or max(overlap_counts.values()) != 1:
            raise AssertionError(f"partial-overlap left invalid day rows: {overlap_counts}")
        results["races"].append(
            {
                "case": "partial-overlap",
                "request_count": 2,
                "success": 1,
                "conflict_409": 1,
                "db_day_counts": overlap_counts,
            }
        )

        adjacent_start = today + timedelta(days=25)
        adjacent = await race_reservations(
            personas,
            manifest=manifest,
            device_id=device_ids[3],
            starts_ends=[
                (adjacent_start, adjacent_start),
                (adjacent_start + timedelta(days=1), adjacent_start + timedelta(days=1)),
            ],
            case="adjacent-days",
        )
        assert_race(adjacent, 2, "adjacent-days")
        adjacent_counts = await db_day_counts(
            factory, device_ids[3], [adjacent_start, adjacent_start + timedelta(days=1)]
        )
        if set(adjacent_counts.values()) != {1}:
            raise AssertionError(f"adjacent-day requests did not both persist: {adjacent_counts}")
        results["races"].append(
            {
                "case": "adjacent-days",
                "request_count": 2,
                "success": 2,
                "conflict_409": 0,
                "db_day_counts": adjacent_counts,
            }
        )

        split_day = today + timedelta(days=27)
        two_devices = await asyncio.gather(
            race_reservations(
                personas,
                manifest=manifest,
                device_id=device_ids[4],
                starts_ends=[(split_day, split_day)],
                case="device-a",
            ),
            race_reservations(
                personas,
                manifest=manifest,
                device_id=device_ids[5],
                starts_ends=[(split_day, split_day)],
                case="device-b",
            ),
        )
        for idx, group in enumerate(two_devices):
            assert_race(group, 1, f"multi-device-{idx}")
        multi_counts = [
            await db_day_counts(factory, device, [split_day])
            for device in (device_ids[4], device_ids[5])
        ]
        if any(list(counts.values()) != [1] for counts in multi_counts):
            raise AssertionError(f"different devices should reserve same date: {multi_counts}")
        results["races"].append(
            {
                "case": "multi-device",
                "request_count": 2,
                "success": 2,
                "conflict_409": 0,
                "db_day_counts": multi_counts,
            }
        )
        return results
    finally:
        for persona in personas:
            try:
                response = await persona.client.post(
                    "/api/v2/auth/logout", headers=persona.headers()
                )
                if response.status_code != 200:
                    raise RuntimeError(f"QA logout cleanup failed: HTTP {response.status_code}")
            finally:
                await persona.client.aclose()
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", default="50,100", help="same-device race sizes")
    parser.add_argument("--manifest", default=str(FIXTURE_FILE))
    parser.add_argument("--output", default=str(RESULTS / "concurrency.json"))
    args = parser.parse_args()
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = ROOT / manifest_path
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = ROOT / output_path
    sizes = [int(item) for item in args.sizes.split(",") if item.strip()]
    if any(size < 2 or size > 100 for size in sizes):
        raise SystemExit("race sizes must be in [2, 100]")
    report = asyncio.run(run(manifest_path, sizes))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
