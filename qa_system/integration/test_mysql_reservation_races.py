from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from app.infrastructure.db.models import Reservation, ReservationItem
from seed_factory import record_created
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[2]
QA = ROOT / "qa_system"


def _fixture_ids() -> dict[str, object]:
    return json.loads((QA / "results" / "seed_ids.json").read_text(encoding="utf-8"))


@pytest.mark.mysql
async def test_mysql_race_on_same_device_day_has_one_201_and_one_409(
    client_factory, qa_state
) -> None:
    ids = _fixture_ids()
    device_id = int(ids["device"][1])
    request_date = date.today() + timedelta(days=12)
    payload = {
        "device_id": device_id,
        "purpose": "QAEVAL concurrent reservation",
        "start_date": request_date.isoformat(),
        "end_date": request_date.isoformat(),
    }
    clients = [await client_factory("student_b"), await client_factory("student_b")]
    try:

        async def submit(client):
            return await client.post(
                "/reservations",
                json=payload,
                headers={"Idempotency-Key": f"qa-race-{uuid4().hex}"},
            )

        responses = await asyncio.gather(*(submit(client) for client in clients))
        assert sorted(response.status_code for response in responses) == [201, 409]
        created = next(response for response in responses if response.status_code == 201)
        data = created.json()["data"]["created"]
        assert len(data) == 1
        record_created("reservation", int(data[0]["id"]))

        engine = create_async_engine(str(qa_state["mysql_dsn"]), pool_pre_ping=True)
        try:
            async with engine.connect() as connection:
                rows = await connection.scalar(
                    select(func.count())
                    .select_from(ReservationItem)
                    .where(
                        ReservationItem.device_id == device_id,
                        ReservationItem.reservation_date == request_date,
                    )
                )
                reservations = await connection.scalar(
                    select(func.count())
                    .select_from(Reservation)
                    .where(
                        Reservation.device_id == device_id,
                        Reservation.start_date == request_date,
                    )
                )
            assert rows == 1
            assert reservations == 1
        finally:
            await engine.dispose()
    finally:
        await asyncio.gather(*(client.aclose() for client in clients))


@pytest.mark.mysql
async def test_same_idempotency_key_returns_same_booking_and_one_row(
    client_factory, qa_state
) -> None:
    ids = _fixture_ids()
    device_id = int(ids["device"][1])
    request_date = date.today() + timedelta(days=16)
    payload = {
        "device_id": device_id,
        "purpose": "QAEVAL idempotency reservation",
        "start_date": request_date.isoformat(),
        "end_date": request_date.isoformat(),
    }
    client = await client_factory("student_b")
    key = f"qa-idempotency-{uuid4().hex}"
    try:
        first = await client.post("/reservations", json=payload, headers={"Idempotency-Key": key})
        second = await client.post("/reservations", json=payload, headers={"Idempotency-Key": key})
        assert first.status_code == 201
        assert second.status_code == 201
        first_id = int(first.json()["data"]["created"][0]["id"])
        second_id = int(second.json()["data"]["created"][0]["id"])
        assert first_id == second_id
        record_created("reservation", first_id)
        engine = create_async_engine(str(qa_state["mysql_dsn"]), pool_pre_ping=True)
        try:
            async with engine.connect() as connection:
                count = await connection.scalar(
                    select(func.count()).select_from(Reservation).where(Reservation.id == first_id)
                )
            assert count == 1
        finally:
            await engine.dispose()
    finally:
        await client.aclose()
