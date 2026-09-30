"""Compare real device-list cache hit/miss and Redis-unavailable DB fallback.

The API comparison uses a unique search term that only matches this run's QA
devices, so it never evicts or replaces a production catalog cache entry.
Redis-unavailable behavior is isolated to a CacheService pointed at an unused
localhost port; the shared Redis service is never stopped or flushed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import socket
import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
from redis.asyncio import Redis
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "qa_eval"))

from app.infrastructure.cache.cache import CacheService  # noqa: E402
from app.infrastructure.db import models  # noqa: E402
from config import BASE_URL, FIXTURE_FILE, REDIS_URL, RESULTS, require_mysql_dsn  # noqa: E402


class Metrics:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def increment(self, name: str, labels: dict[str, object] | None = None) -> None:
        del labels
        self.counts[name] = self.counts.get(name, 0) + 1


async def _mysql_snapshot(engine) -> dict[str, int]:
    async with engine.connect() as connection:
        rows = await connection.execute(
            text(
                "SHOW GLOBAL STATUS WHERE Variable_name IN "
                "('Queries','Slow_queries','Threads_running')"
            )
        )
        return {str(key): int(value) for key, value in rows}


async def _measure_api_and_fallback() -> dict[str, Any]:
    manifest_path = FIXTURE_FILE if FIXTURE_FILE.is_absolute() else ROOT / FIXTURE_FILE
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    user = manifest["accounts"]["students"]["CSE"][0]
    college_id = int(manifest["college_ids"]["CSE"])
    search = f"qa-device-{manifest['run_id']}"
    fingerprint_payload = {
        "search": search,
        "lab_id": None,
        "status": None,
        "page": 1,
        "page_size": 20,
        "viewer": "member",
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:24]
    redis = Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=1)
    engine = create_async_engine(
        require_mysql_dsn(), pool_pre_ping=True, pool_size=2, max_overflow=0
    )
    try:
        version_key = f"lab:v2:cache:catalog:version:college:{college_id}"
        version = await redis.get(version_key)
        if version is None:
            await redis.set(version_key, "1", nx=True)
            version = await redis.get(version_key)
        cache_key = f"lab:v2:catalog:devices:college:{college_id}:v{version}:{fingerprint}"
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=20) as client:
            csrf = (await client.get("/api/v2/auth/csrf")).json()["data"]["csrf_token"]
            login = await client.post(
                "/api/v2/auth/login",
                json={"username": user["username"], "password": manifest["password"]},
                headers={"Origin": "http://127.0.0.1:5173", "X-CSRF-Token": csrf},
            )
            login.raise_for_status()
            csrf = login.json()["data"]["csrf_token"]

            async def request_list() -> tuple[float, str, int]:
                started = time.perf_counter()
                response = await client.get(
                    "/api/v2/devices",
                    params={"search": search, "page": 1, "page_size": 20},
                )
                elapsed = (time.perf_counter() - started) * 1000
                response.raise_for_status()
                body = response.json()["data"]
                if body["total"] != 6 or len(body["items"]) != 6:
                    raise AssertionError(
                        f"unique QA search returned unexpected catalog: {body['total']=}"
                    )
                digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
                return elapsed, digest, int(body["total"])

            cold_samples: list[float] = []
            cold_digests: list[str] = []
            cold_db_stats: list[dict[str, int]] = []
            cold_redis_stats: list[dict[str, int]] = []
            for _ in range(3):
                await redis.delete(cache_key, f"{cache_key}:load-lock")
                cold_db_stats.append(await _mysql_snapshot(engine))
                cold_redis_stats.append(await redis.info("stats"))
                elapsed, digest, _ = await request_list()
                cold_samples.append(elapsed)
                cold_digests.append(digest)
            cold_db_end = await _mysql_snapshot(engine)

            # Populate once, then measure three hits with the same exact key.
            await redis.delete(cache_key, f"{cache_key}:load-lock")
            await request_list()
            warm_samples: list[float] = []
            warm_digests: list[str] = []
            warm_db_stats: list[dict[str, int]] = []
            warm_redis_stats: list[dict[str, int]] = []
            for _ in range(3):
                warm_db_stats.append(await _mysql_snapshot(engine))
                warm_redis_stats.append(await redis.info("stats"))
                elapsed, digest, _ = await request_list()
                warm_samples.append(elapsed)
                warm_digests.append(digest)
            warm_db_end = await _mysql_snapshot(engine)
            if len(set(cold_digests + warm_digests)) != 1:
                raise AssertionError("device list content changed between cache miss and hit")

            await client.post(
                "/api/v2/auth/logout",
                headers={"Origin": "http://127.0.0.1:5173", "X-CSRF-Token": csrf},
            )

        # Point only this probe's cache client at an unused local port.
        with socket.socket() as probe_socket:
            probe_socket.settimeout(0.2)
            if probe_socket.connect_ex(("127.0.0.1", 6399)) == 0:
                raise RuntimeError("port 6399 is in use; refusing to simulate Redis failure there")
        unavailable_redis = Redis.from_url(
            "redis://127.0.0.1:6399/15",
            decode_responses=True,
            socket_connect_timeout=0.1,
            socket_timeout=0.1,
            retry_on_timeout=False,
        )
        metrics = Metrics()
        cache = CacheService(
            unavailable_redis,
            SimpleNamespace(
                cache_default_ttl_seconds=60,
                cache_negative_ttl_seconds=10,
                cache_ttl_jitter_seconds=0,
                cache_hot_key_lock_seconds=1,
                cache_hot_key_wait_seconds=0.01,
            ),
            metrics,
        )
        async with engine.connect() as connection:
            expected_count = int(
                await connection.scalar(
                    select(func.count(models.Device.id)).where(
                        models.Device.college_id == college_id,
                        models.Device.status != "DELETED",
                    )
                )
                or 0
            )
        started = time.perf_counter()
        fallback = await cache.get_or_set_json(
            f"qa_eval:redis-down:{manifest['run_id']}",
            lambda: _count_devices(engine, college_id),
        )
        fallback_ms = (time.perf_counter() - started) * 1000
        if fallback != {"count": expected_count}:
            raise AssertionError(
                f"Redis-unavailable cache read must return authoritative DB result: {fallback}"
            )
        await unavailable_redis.aclose()

        return {
            "cache_key_scope": "unique QA device search; key omitted from report",
            "api_cache_miss": {
                "samples_ms": cold_samples,
                "median_ms": statistics.median(cold_samples),
                "mysql_queries_delta": _delta(cold_db_stats[0], cold_db_end),
                "redis_stats_before_each": _redis_counters(cold_redis_stats),
            },
            "api_cache_hit": {
                "samples_ms": warm_samples,
                "median_ms": statistics.median(warm_samples),
                "mysql_queries_delta": _delta(warm_db_stats[0], warm_db_end),
                "redis_stats_before_each": _redis_counters(warm_redis_stats),
                "content_identical": True,
            },
            "redis_unavailable_cache_fallback": {
                "status": "passed",
                "result_count": fallback["count"],
                "expected_count": expected_count,
                "latency_ms": round(fallback_ms, 2),
                "cache_error_metric": metrics.counts.get("cache_errors_total", 0),
                "shared_redis_stopped": False,
            },
        }
    finally:
        await redis.aclose()
        await engine.dispose()


async def _count_devices(engine, college_id: int) -> dict[str, int]:
    async with engine.connect() as connection:
        count = await connection.scalar(
            select(func.count(models.Device.id)).where(
                models.Device.college_id == college_id,
                models.Device.status != "DELETED",
            )
        )
    return {"count": int(count or 0)}


def _delta(start: dict[str, int], end: dict[str, int]) -> dict[str, int]:
    return {key: end.get(key, 0) - value for key, value in start.items()}


def _redis_counters(rows: list[dict[str, Any]]) -> list[dict[str, int]]:
    keys = ("keyspace_hits", "keyspace_misses", "total_commands_processed")
    return [{key: int(row.get(key, 0)) for key in keys} for row in rows]


def main() -> None:
    result = asyncio.run(_measure_api_and_fallback())
    output = RESULTS / "cache-comparison.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({**result, "output": str(output)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
