"""Measure MySQL -> Outbox -> Redis Pub/Sub -> SSE delivery at 10/50/100 streams.

Requires a dedicated QA API process with RedisNotificationRelay enabled and the
SSE pending-per-IP cap raised to at least 100. It logs in as unique QA students,
opens 5 EventSource-equivalent streams per student, persists one due Outbox task
per user, then processes each task through the production OutboxWorker handler.
Only the wake-up hint is carried by Redis; the browser stream reads the committed
Notification row and is checked for one strictly increasing sequence per user.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "qa_eval"))

from app.core.settings import Settings  # noqa: E402
from app.infrastructure.db import models  # noqa: E402
from app.infrastructure.notifications.realtime import NotificationHub  # noqa: E402
from app.infrastructure.notifications.relay import RedisNotificationRelay  # noqa: E402
from app.infrastructure.tasks.worker import OutboxWorker, utcnow_naive  # noqa: E402
from config import FIXTURE_FILE, REDIS_URL, RESULTS, require_mysql_dsn  # noqa: E402

SIZES = (10, 50, 100)
STREAMS_PER_USER = 5
PAGE_NAME = "qa_eval_sse_fanout"


class StreamResult:
    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        self.expected_title = ""
        self.ready = asyncio.Event()
        self.received: asyncio.Future[dict[str, Any]] | None = None
        self.connected_at = 0.0


async def _consume(client: httpx.AsyncClient, result: StreamResult, origin: str) -> None:
    loop = asyncio.get_running_loop()
    result.received = loop.create_future()
    result.connected_at = time.perf_counter()
    event_name = ""
    event_id = ""
    data: dict[str, Any] = {}
    async with client.stream(
        "GET",
        "/api/v2/notifications/stream",
        headers={"Origin": origin, "Accept": "text/event-stream"},
        timeout=None,
    ) as response:
        if response.status_code != 200:
            raise AssertionError(f"SSE connect rejected with HTTP {response.status_code}")
        async for line in response.aiter_lines():
            if line.startswith("id:"):
                event_id = line[3:].strip()
            elif line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:].strip())
            elif line == "":
                if event_name == "stream-ready":
                    result.ready.set()
                elif (
                    event_name == "notification"
                    and data.get("title") == result.expected_title
                    and not result.received.done()
                ):
                    result.received.set_result(
                        {"id": event_id, "data": data, "received_at": time.perf_counter()}
                    )
                event_name, event_id, data = "", "", {}


async def _insert_tasks(
    factory, users: list[dict[str, Any]], college_id: int, task_key_prefix: str
) -> list[str]:
    now = utcnow_naive()
    task_keys = []
    async with factory() as session:
        for user in users:
            user_id = int(user["user_id"])
            task_key = f"{task_key_prefix}:{user_id}"
            task_keys.append(task_key)
            session.add(
                models.OutboxTask(
                    task_key=task_key,
                    task_type="NOTIFICATION",
                    aggregate_key=f"notification:{user_id}",
                    college_id=college_id,
                    payload={
                        "user_id": user_id,
                        "college_id": college_id,
                        "type": "QA_SSE_LOAD",
                        "title": task_key_prefix,
                        "content": "isolated end-to-end SSE fanout benchmark",
                        "related_id": None,
                        "related_type": None,
                    },
                    status="PENDING",
                    attempts=0,
                    execute_at=now,
                )
            )
        await session.commit()
    return task_keys


async def _task_state(factory, task_key: str) -> dict[str, Any]:
    async with factory() as session:
        task = await session.scalar(
            select(models.OutboxTask).where(models.OutboxTask.task_key == task_key)
        )
        if task is None:
            return {"exists": False}
        return {
            "exists": True,
            "status": task.status,
            "execute_at": task.execute_at.isoformat(),
            "attempts": task.attempts,
            "claimed_at": task.claimed_at.isoformat() if task.claimed_at else None,
            "aggregate_key": task.aggregate_key,
        }


async def _drive_task(worker: OutboxWorker, factory, task_key: str) -> str:
    """Claim the fixture task or wait for the configured per-user predecessor."""
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        claimed = await worker._claim_one(only_task_key=task_key)
        if claimed is not None:
            await worker._process_claimed(claimed)
            return "qa_eval_worker"
        state = await _task_state(factory, task_key)
        if not state.get("exists"):
            raise AssertionError(f"Outbox task disappeared before delivery: {task_key}")
        if state.get("status") == "COMPLETED":
            return "other_worker"
        if state.get("status") == "FAILED":
            raise AssertionError(f"Outbox task failed before SSE delivery: {state}")
        # A predecessor for this user may be PROCESSING. The production queue
        # intentionally serializes equal aggregate keys; wait for that durable
        # state transition, then race again for the fixture task.
        await asyncio.sleep(0.05)
    raise TimeoutError(
        f"Outbox task did not become deliverable: {await _task_state(factory, task_key)}"
    )


async def _wait_completed(factory, task_keys: list[str]) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        states = [await _task_state(factory, key) for key in task_keys]
        if all(state.get("status") == "COMPLETED" for state in states):
            return
        if any(state.get("status") == "FAILED" for state in states):
            raise AssertionError(f"notification Outbox task entered FAILED: {states}")
        await asyncio.sleep(0.05)
    raise TimeoutError(f"notification Outbox tasks did not complete: {states}")


async def _run() -> dict[str, Any]:
    manifest_path = FIXTURE_FILE if FIXTURE_FILE.is_absolute() else ROOT / FIXTURE_FILE
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    origin = "http://127.0.0.1:5173"
    base_url = __import__("os").getenv("QA_SSE_BASE_URL", "http://127.0.0.1:8003").rstrip("/")
    users = manifest["accounts"]["students"]["CSE"][:20]
    college_id = int(manifest["college_ids"]["CSE"])
    clients: list[httpx.AsyncClient] = []
    async_engine = create_async_engine(
        require_mysql_dsn(), pool_pre_ping=True, pool_size=8, max_overflow=8
    )
    factory = async_sessionmaker(async_engine, expire_on_commit=False, autoflush=False)
    probe_app = FastAPI()
    probe_app.state.settings = Settings(
        environment="test",
        mysql_dsn=require_mysql_dsn(),
        redis_url=REDIS_URL,
        enable_workers=False,
    )
    probe_app.state.notification_hub = NotificationHub()
    publisher = Redis.from_url(REDIS_URL, decode_responses=True)
    relay = RedisNotificationRelay(probe_app.state.notification_hub, publisher, REDIS_URL)
    probe_app.state.notification_relay = relay
    probe_app.state.session_factory = factory
    worker = OutboxWorker(probe_app, poll_seconds=0.1)
    try:
        # One authenticated, isolated cookie jar per student. Five simultaneous
        # streams per account exercise the configured per-user connection cap.
        for account in users:
            client = httpx.AsyncClient(
                base_url=base_url,
                timeout=20,
                limits=httpx.Limits(
                    max_connections=STREAMS_PER_USER + 2, max_keepalive_connections=2
                ),
            )
            csrf = (await client.get("/api/v2/auth/csrf")).json()["data"]["csrf_token"]
            login = await client.post(
                "/api/v2/auth/login",
                json={"username": account["username"], "password": manifest["password"]},
                headers={"Origin": origin, "X-CSRF-Token": csrf},
            )
            login.raise_for_status()
            clients.append(client)

        results: dict[str, Any] = {
            "transport": "SSE",
            "delivery_path": "MySQL Outbox -> Redis Pub/Sub wake-up -> MySQL cursor -> SSE",
            "max_streams_per_user": STREAMS_PER_USER,
            "repetitions": 3,
            "profiles": [],
        }
        previous_sequences: dict[int, int] = {}
        for size in SIZES:
            distinct_users = users[: size // STREAMS_PER_USER]
            repetition_summaries: list[dict[str, Any]] = []
            all_latencies: list[float] = []
            for repetition in range(1, 4):
                streams: list[StreamResult] = []
                stream_tasks: list[asyncio.Task[None]] = []
                for account in distinct_users:
                    user_id = int(account["user_id"])
                    client = clients[users.index(account)]
                    for _ in range(STREAMS_PER_USER):
                        stream_result = StreamResult(user_id)
                        streams.append(stream_result)
                        stream_tasks.append(
                            asyncio.create_task(_consume(client, stream_result, origin))
                        )

                try:
                    await asyncio.wait_for(
                        asyncio.gather(*(stream.ready.wait() for stream in streams)), timeout=20
                    )
                    task_prefix = (
                        f"{PAGE_NAME}:{manifest['run_id']}:{uuid.uuid4().hex[:8]}:"
                        f"{size}:{repetition}"
                    )
                    for stream in streams:
                        stream.expected_title = task_prefix
                    task_keys = await _insert_tasks(
                        factory, distinct_users, college_id, task_prefix
                    )
                    start_time = time.perf_counter()
                    worker_sources = [await _drive_task(worker, factory, key) for key in task_keys]
                    received = await asyncio.wait_for(
                        asyncio.gather(*(asyncio.shield(item.received) for item in streams)),
                        timeout=30,
                    )
                    await _wait_completed(factory, task_keys)
                    elapsed_ms = [(event["received_at"] - start_time) * 1000 for event in received]
                    all_latencies.extend(elapsed_ms)
                    by_user: dict[int, list[int]] = defaultdict(list)
                    for item, event in zip(streams, received, strict=True):
                        sequence = int(event["id"])
                        if int(event["data"]["deliverySequence"]) != sequence:
                            raise AssertionError("SSE frame ID and payload sequence diverged")
                        if event["data"].get("title") != task_prefix:
                            raise AssertionError(
                                "stream received a different user's or unrelated notification"
                            )
                        by_user[item.user_id].append(sequence)
                    duplicates_or_gaps = {
                        str(user_id): sequences
                        for user_id, sequences in by_user.items()
                        if len(set(sequences)) != 1
                    }
                    if duplicates_or_gaps or len(received) != size:
                        raise AssertionError(
                            f"fanout lost or reordered per-user sequence: {duplicates_or_gaps}"
                        )
                    for user_id, sequences in by_user.items():
                        sequence = sequences[0]
                        if (
                            user_id in previous_sequences
                            and sequence <= previous_sequences[user_id]
                        ):
                            raise AssertionError(
                                f"user delivery sequence did not increase: {user_id}"
                            )
                        previous_sequences[user_id] = sequence
                    repetition_summaries.append(
                        {
                            "repetition": repetition,
                            "received": len(received),
                            "median_push_ms": round(statistics.median(elapsed_ms), 2),
                            "p95_push_ms": round(
                                sorted(elapsed_ms)[max(0, int(len(elapsed_ms) * 0.95) - 1)], 2
                            ),
                            "max_push_ms": round(max(elapsed_ms), 2),
                            "outbox_workers": worker_sources,
                        }
                    )
                finally:
                    for task in stream_tasks:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*stream_tasks, return_exceptions=True)

            results["profiles"].append(
                {
                    "connections": size,
                    "users": len(distinct_users),
                    "repetitions": repetition_summaries,
                    "median_push_ms": round(statistics.median(all_latencies), 2),
                    "p95_push_ms": round(
                        sorted(all_latencies)[max(0, int(len(all_latencies) * 0.95) - 1)], 2
                    ),
                    "max_push_ms": round(max(all_latencies), 2),
                    "sequence_per_user": (
                        "strictly increasing; one unique sequence observed identically "
                        "by all 5 tabs"
                    ),
                    "all_connections_received": True,
                }
            )

        output = RESULTS / "sse-fanout.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        return {**results, "output": str(output)}
    finally:
        for client in clients:
            await client.aclose()
        await publisher.aclose()
        await relay.stop()
        await async_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(json.dumps(asyncio.run(_run()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
