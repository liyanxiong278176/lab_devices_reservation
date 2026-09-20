"""Small black-box reservation contention benchmark.

Run against a local API after seeding one device:

    uv run python benchmarks/reservation_concurrency.py \
      --base-url http://127.0.0.1:8000/api/v2 \
      --token "$ACCESS_TOKEN" --device-id 1 --date 2030-01-01 --clients 100

The expected invariant is exactly one successful reservation for the same
device-day; all other requests should be a typed 409 conflict. The script is
deliberately read-only with respect to setup and never deletes data.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass
from datetime import date

import httpx


@dataclass
class Result:
    status_code: int
    code: str | None


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--device-id", required=True, type=int)
    parser.add_argument("--date", required=True, type=date.fromisoformat)
    parser.add_argument("--clients", default=100, type=int)
    args = parser.parse_args()
    payload = {
        "device_id": args.device_id,
        "start_date": args.date.isoformat(),
        "end_date": args.date.isoformat(),
        "purpose": "concurrency benchmark",
    }
    headers = {"Authorization": f"Bearer {args.token}"}
    started = time.perf_counter()
    async with httpx.AsyncClient(base_url=args.base_url, timeout=30) as client:

        async def one(index: int) -> Result:
            response = await client.post(
                "/reservations",
                json=payload,
                headers={**headers, "Idempotency-Key": f"benchmark-{index}"},
            )
            try:
                body = response.json()
            except json.JSONDecodeError:
                body = {}
            return Result(response.status_code, body.get("code"))

        results = await asyncio.gather(*(one(index) for index in range(args.clients)))
    elapsed_ms = (time.perf_counter() - started) * 1000
    summary = {
        "clients": args.clients,
        "elapsed_ms": round(elapsed_ms, 2),
        "success_201": sum(result.status_code == 201 for result in results),
        "conflict_409": sum(result.status_code == 409 for result in results),
        "other": [
            {"status": result.status_code, "code": result.code}
            for result in results
            if result.status_code not in {201, 409}
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["success_201"] != 1 or summary["other"]:
        raise SystemExit("contention invariant failed")


if __name__ == "__main__":
    asyncio.run(main())
