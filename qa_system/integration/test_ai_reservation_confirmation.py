from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from app.infrastructure.db.models import AiConfirmation, AiRun, Reservation, ReservationItem
from seed_factory import record_created
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[2]
QA = ROOT / "qa_system"


def _fixture_ids() -> dict[str, object]:
    return json.loads((QA / "results" / "seed_ids.json").read_text(encoding="utf-8"))


async def _count_reservations(qa_state: dict[str, object], device_id: int, day: date) -> int:
    engine = create_async_engine(str(qa_state["mysql_dsn"]), pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            count = await connection.scalar(
                select(func.count())
                .select_from(ReservationItem)
                .where(
                    ReservationItem.device_id == device_id,
                    ReservationItem.reservation_date == day,
                )
            )
        return int(count or 0)
    finally:
        await engine.dispose()


@pytest.mark.ai_integration
async def test_ai_mutating_tool_requires_explicit_idempotent_confirmation(
    client_factory, qa_state
) -> None:
    ids = _fixture_ids()
    device_id = int(ids["device"][1])
    request_date = date.today() + timedelta(days=23)
    student = await client_factory("student_b")
    try:
        conversation_response = await student.post(
            "/ai/conversations",
            json={"title": "QAEVAL AI reservation confirmation"},
        )
        assert conversation_response.status_code == 201, conversation_response.text
        conversation_id = int(conversation_response.json()["data"]["id"])
        record_created("ai_conversation", conversation_id)

        events: list[dict[str, object]] = []
        async with student.stream(
            "POST",
            f"/ai/conversations/{conversation_id}/stream",
            json={
                "content": (
                    f"请帮我预约设备编号 {device_id}，日期 {request_date.isoformat()}，"
                    "用于验证 AI 操作必须先确认。"
                )
            },
        ) as response:
            assert response.status_code == 200, (await response.aread()).decode("utf-8", "replace")
            assert response.headers.get("content-type", "").startswith("text/event-stream")
            data_line = ""
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data_line = line[6:]
                elif not line and data_line:
                    events.append(json.loads(data_line))
                    data_line = ""
                    if events[-1].get("type") in {"done", "error"}:
                        break

        by_type = {str(event.get("type")): event for event in events}
        assert "error" not in by_type, events
        assert "confirmation_required" in by_type, events
        assert by_type.get("done", {}).get("status") == "WAITING_CONFIRMATION", events
        confirmation_id = int(by_type["confirmation_required"]["confirmation_id"])
        record_created("ai_confirmation", confirmation_id)
        assert by_type["confirmation_required"]["tool_name"] == "create_reservation"
        run_id = int(by_type.get("run_started", {}).get("run_id", 0))
        if run_id:
            record_created("ai_run", run_id)
        assert await _count_reservations(qa_state, device_id, request_date) == 0, (
            "AI tool changed reservation data before confirmation"
        )

        confirmed = await student.post(
            f"/ai/confirmations/{confirmation_id}/confirm",
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["data"]["status"] == "EXECUTED"
        created = confirmed.json()["data"]["data"]
        assert isinstance(created.get("created"), list) and created["created"], created
        reservation = created["created"][0]
        record_created("reservation", int(reservation["id"]))
        assert int(reservation["device_id"]) == device_id, created

        retry = await student.post(f"/ai/confirmations/{confirmation_id}/confirm")
        assert retry.status_code == 200, retry.text
        assert retry.json()["data"]["already_processed"] is True
        assert await _count_reservations(qa_state, device_id, request_date) == 1

        engine = create_async_engine(str(qa_state["mysql_dsn"]), pool_pre_ping=True)
        try:
            async with engine.connect() as connection:
                reservation_count = await connection.scalar(
                    select(func.count())
                    .select_from(Reservation)
                    .where(Reservation.id == int(reservation["id"]))
                )
                confirmation_status = await connection.scalar(
                    select(AiConfirmation.status).where(AiConfirmation.id == confirmation_id)
                )
                run_status = (
                    await connection.scalar(select(AiRun.status).where(AiRun.id == run_id))
                    if run_id
                    else None
                )
            assert reservation_count == 1
            assert confirmation_status == "EXECUTED"
            assert run_status == "COMPLETED"
        finally:
            await engine.dispose()
    finally:
        await student.aclose()
