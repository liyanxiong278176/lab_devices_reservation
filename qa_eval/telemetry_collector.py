"""Sample local API process, MySQL, Redis, and optional Docker metrics to JSONL."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil
from config import REDIS_URL, require_mysql_dsn
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


def _docker_stats() -> list[dict[str, str]] | None:
    try:
        completed = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}"],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    rows = []
    for line in completed.stdout.splitlines():
        fields = line.split("|", 2)
        if len(fields) == 3:
            rows.append({"name": fields[0], "cpu": fields[1], "memory": fields[2]})
    return rows


async def _database_metrics(engine) -> dict[str, Any]:
    wanted = {
        "Threads_connected",
        "Threads_running",
        "Queries",
        "Slow_queries",
        "Innodb_buffer_pool_reads",
        "Innodb_buffer_pool_read_requests",
    }
    async with engine.connect() as connection:
        rows = await connection.execute(text("SHOW GLOBAL STATUS"))
        values = {str(name): str(value) for name, value in rows if name in wanted}
        process_count = await connection.scalar(
            text("SELECT COUNT(*) FROM information_schema.processlist")
        )
    return {"global_status": values, "processlist_count": process_count}


async def collect(seconds: int, interval: float, output: Path, api_pid: int | None) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(
        require_mysql_dsn(), pool_pre_ping=True, pool_size=2, max_overflow=0
    )
    redis = Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=1)
    process = psutil.Process(api_pid) if api_pid else None
    deadline = time.monotonic() + seconds
    try:
        with output.open("w", encoding="utf-8", newline="\n") as stream:
            while time.monotonic() < deadline:
                row: dict[str, Any] = {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "system_cpu_percent": psutil.cpu_percent(interval=None),
                    "system_memory_percent": psutil.virtual_memory().percent,
                }
                if process is not None:
                    try:
                        row["api_process"] = {
                            "pid": api_pid,
                            "cpu_percent": process.cpu_percent(interval=None),
                            "rss_bytes": process.memory_info().rss,
                            "threads": process.num_threads(),
                            "open_files": len(process.open_files()),
                        }
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        row["api_process"] = {"pid": api_pid, "unavailable": True}
                try:
                    info = await redis.info()
                    row["redis"] = {
                        key: info.get(key)
                        for key in (
                            "connected_clients",
                            "used_memory",
                            "keyspace_hits",
                            "keyspace_misses",
                            "total_connections_received",
                        )
                    }
                except Exception as exc:  # keep the run observable during a Redis fault
                    row["redis"] = {"error_type": type(exc).__name__}
                try:
                    row["mysql"] = await _database_metrics(engine)
                except Exception as exc:  # keep sampling OS data if a dependency fails
                    row["mysql"] = {"error_type": type(exc).__name__}
                row["docker"] = _docker_stats()
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                stream.flush()
                await asyncio.sleep(interval)
    finally:
        await redis.aclose()
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, required=True)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--api-pid", type=int)
    args = parser.parse_args()
    if args.seconds < 1 or args.interval <= 0:
        raise SystemExit("seconds and interval must be positive")
    output = args.output if args.output.is_absolute() else Path.cwd() / args.output
    asyncio.run(collect(args.seconds, args.interval, output, args.api_pid))
    print(f"resource samples written: {output}")


if __name__ == "__main__":
    main()
