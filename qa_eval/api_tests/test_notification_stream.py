"""SSE interface/integration tests backed by real MySQL, Redis, and API sessions."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from app.infrastructure.db import models
from sqlalchemy import func, select


async def _parse_until(response, target_event: str) -> list[dict[str, object]]:
    """Read complete SSE frames only; stop as soon as the requested event arrives."""
    frames: list[dict[str, object]] = []
    current: dict[str, object] = {}
    async for line in response.aiter_lines():
        if line.startswith("id:"):
            current["id"] = line[3:].strip()
        elif line.startswith("event:"):
            current["event"] = line[6:].strip()
        elif line.startswith("data:"):
            current["data"] = json.loads(line[5:].strip())
        elif not line and current:
            frames.append(current)
            if current.get("event") == target_event:
                return frames
            current = {}
    return frames


@pytest.mark.asyncio
async def test_reconnect_replays_newest_100_in_sequence_and_http_history_has_all(
    client_factory, manifest, mysql_factory
):
    """Integration: replay cap, sequence order, overflow metadata, and HTTP fallback."""
    student = await client_factory("sse", "CSE")
    now = datetime.now(UTC).replace(tzinfo=None)
    async with mysql_factory() as session:
        await session.scalar(
            select(models.User.id).where(models.User.id == student.user_id).with_for_update()
        )
        previous_head = int(
            await session.scalar(
                select(func.max(models.Notification.delivery_sequence)).where(
                    models.Notification.user_id == student.user_id
                )
            )
            or 0
        )
        total_before = int(
            await session.scalar(
                select(func.count(models.Notification.id)).where(
                    models.Notification.user_id == student.user_id
                )
            )
            or 0
        )
        session.add_all(
            [
                models.Notification(
                    user_id=student.user_id,
                    college_id=int(manifest["college_ids"]["CSE"]),
                    type="QA_REPLAY",
                    title=f"qa-eval-replay-{index:03d}",
                    content="isolated SSE replay row",
                    related_id=None,
                    related_type=None,
                    source_task_key=f"qa-eval-{manifest['run_id']}-replay-{index:03d}",
                    is_read=False,
                    delivery_sequence=previous_head + index,
                    created_at=now,
                    updated_at=now,
                )
                for index in range(1, 102)
            ]
        )
        await session.commit()
    assert previous_head == 0 and total_before == 0, "dedicated SSE fixture user must start empty"

    async with student.client.stream(
        "GET",
        "/api/v2/notifications/stream",
        headers={"Last-Event-ID": str(previous_head)},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        frames = await _parse_until(response, "batch-complete")

    replayed = [frame for frame in frames if frame.get("event") == "notification"]
    summary = next(frame["data"] for frame in frames if frame.get("event") == "batch-complete")
    sequences = [int(frame["id"]) for frame in replayed]
    assert len(replayed) == 100
    assert sequences == list(range(previous_head + 2, previous_head + 102))
    assert [frame["data"]["deliverySequence"] for frame in replayed] == sequences
    assert summary == {
        "replay": True,
        "deliveredCount": 100,
        "omittedCount": 1,
        "historySyncRequired": True,
    }
    assert (
        int(next(frame["id"] for frame in frames if frame.get("event") == "batch-complete"))
        == previous_head + 101
    )

    history = await student.client.get("/api/v2/notifications/mine?page=1&size=100")
    assert history.status_code == 200
    assert history.json()["data"]["total"] == total_before + 101
    history_rows = history.json()["data"]["records"]
    replay_titles = {row["title"] for row in history_rows}
    assert all(f"qa-eval-replay-{index:03d}" in replay_titles for index in range(2, 102))
    assert "qa-eval-replay-001" not in replay_titles


@pytest.mark.asyncio
async def test_logout_closes_the_active_sse_stream(manifest):
    """Integration: session revocation wakes and closes its authenticated stream."""
    from config import BASE_URL
    from httpx import AsyncClient

    account = manifest["accounts"]["sse"]
    client = AsyncClient(base_url=BASE_URL, timeout=10)
    try:
        csrf = (await client.get("/api/v2/auth/csrf")).json()["data"]["csrf_token"]
        login = await client.post(
            "/api/v2/auth/login",
            json={"username": account["username"], "password": manifest["password"]},
            headers={"Origin": "http://127.0.0.1:5173", "X-CSRF-Token": csrf},
        )
        assert login.status_code == 200
        csrf = login.json()["data"]["csrf_token"]

        async with client.stream("GET", "/api/v2/notifications/stream") as response:
            assert response.status_code == 200
            iterator = response.aiter_lines()
            ready_seen = False
            event_name = ""
            async for line in iterator:
                if line.startswith("event:"):
                    event_name = line[6:].strip()
                elif not line and event_name:
                    ready_seen = event_name == "stream-ready"
                    event_name = ""
                    if ready_seen:
                        break
            assert ready_seen

            logout = await client.post(
                "/api/v2/auth/logout",
                headers={"Origin": "http://127.0.0.1:5173", "X-CSRF-Token": csrf},
            )
            assert logout.status_code == 200
            revoked = False
            async for line in iterator:
                if line == "event: auth-revoked":
                    revoked = True
                if revoked and line == "":
                    break
            assert revoked, "logout should promptly send auth-revoked to the live SSE connection"
    finally:
        await client.aclose()
